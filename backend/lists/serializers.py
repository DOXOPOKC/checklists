import base64
import imghdr
import os
import uuid
from collections import defaultdict

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.utils import timezone
from django_q.tasks import async_task
from rest_framework import serializers

from notifications import tasks
from user_profile import models as umodels

from . import models


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Question
        fields = ('id', 'text', 'order', 'required',
                  'type', 'choices', 'key_choices')


class SurveySerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True)

    class Meta:
        model = models.Survey
        fields = ('id', 'name', 'description', 'questions')


class SurveyListSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Survey
        fields = ('id', 'name', 'description')


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Report
        fields = ('id', 'name', 'date_from', 'date_to', 'checklists')


class AnswerSerializer(serializers.ModelSerializer):
    question = QuestionSerializer()

    class Meta:
        model = models.Answer
        depth = 1
        fields = ('id', 'question', 'body')


class ResponseListSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True)
    user_text = serializers.SerializerMethodField()

    def get_user_text(self, obj):
        email = obj.user.email
        if obj.user.first_name and obj.user.last_name:
            res = f"{obj.user.first_name[0]}. {obj.user.last_name} <{email}>"
        else:
            res = email
        return res

    class Meta:
        model = models.Response
        fields = ('id', 'created', 'survey', 'answers', 'user_text')


class Base64ImageField(serializers.ImageField):

    def to_internal_value(self, data):
        if isinstance(data, str):
            if ('http://' in data) or ('https://' in data):
                complete_file_name = data.split('/')[-1]
                path = os.path.join(settings.MEDIA_ROOT,
                                    'files',
                                    complete_file_name)
                with open(path, "rb") as imageFile:
                    decoded_file = imageFile.read()
            elif 'data:' in data and ';base64,' in data:
                header, data = data.split(';base64,')

                try:
                    decoded_file = base64.b64decode(data)
                except TypeError:
                    self.fail('invalid_image')

                file_name = str(uuid.uuid4())[:12]
                file_extension = self.get_file_extension(
                    file_name, decoded_file)

                complete_file_name = f"{file_name}.{file_extension}"

            data = ContentFile(decoded_file, name=complete_file_name)

        return super(Base64ImageField, self).to_internal_value(data)

    def get_file_extension(self, file_name, decoded_file):
        extension = imghdr.what(file_name, decoded_file)
        extension = "jpg" if extension == "jpeg" else extension

        return extension


class AttachmentSerializer(serializers.HyperlinkedModelSerializer):
    file = Base64ImageField(max_length=None, use_url=True)

    class Meta:
        model = models.Attachment
        fields = ('file', 'name')


class ResponseSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True)
    photo = AttachmentSerializer(many=True, required=False)
    user_text = serializers.SerializerMethodField()

    def get_user_text(self, obj):
        email = obj.user.email
        if obj.user.first_name and obj.user.last_name:
            res = f"{obj.user.first_name[0]}. {obj.user.last_name} <{email}>"
        else:
            res = email
        return res

    class Meta:
        model = models.Response
        fields = ('id', 'created', 'updated', 'survey',
                  "answers", 'photo', 'user_text')

    def create(self, validated_data):
        answers = validated_data.pop('answers')
        photos = validated_data.pop('photo')
        response = models.Response.objects.create(**validated_data)

        for answer in answers:
            models.Answer.objects.create(response=response, **answer)

        content_type = ContentType.objects.get(model='response',
                                               app_label='lists')
        for photo in photos:
            models.Attachment.objects.create(
                object_id=response.id, content_type=content_type, **photo)

        return response

    def update(self, instance, validated_data):
        instance.created = validated_data.get('created', instance.created)
        instance.updated = validated_data.get('updated', instance.updated)
        instance.survey = validated_data.get('survey', instance.survey)

        answers = self.initial_data['answers']
        for answer in answers:
            if answer.get('id', None):
                ans = models.Answer.objects.get(id=answer['id'])
                ans.body = answer['body']
                ans.updated = timezone.now()
                ans.save()
            else:
                models.Answer.objects.create(
                    question=answer['question'],
                    response=instance,
                    body=answer["body"],
                    created=timezone.now(),
                    updated=timezone.now(),
                )

        instance.photo.all().delete()

        photos = validated_data.get('photo', [])
        content_type = ContentType.objects.get(model='response',
                                               app_label='lists')
        for photo in photos:
            models.Attachment.objects.create(
                object_id=instance.id, content_type=content_type, **photo)
        async_task(tasks.basic_report, instance)
        return instance

    def validate(self, attrs):
        in_survey_count = len(
            [x for x in attrs['survey'].questions.all() if x.required is True])

        in_response_count = len(
            [x for x in attrs['answers'] if x['question']['required'] is True])

        if attrs['photo'] is not []:
            in_response_count += 1

        if in_response_count < in_survey_count:
            raise serializers.ValidationError(
                "Не все обязательные поля заполнены")

        attrs['answers'] = self.initial_data['answers']
        for x in attrs['answers']:
            x['question'] = models.Question(**x['question'])
        return super().validate(attrs)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = umodels.UserProfile
        fields = ('id', 'email', 'first_name', 'last_name', 'position')


class MapNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.MapNode
        fields = ('name', 'lat', 'lon', 'response', 'answer')

# Begin report generation


class ReportQuestionSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        self.responses = kwargs.pop('responses', None)
        self.answers = kwargs.pop('answers', None)
        self.photos = kwargs.pop('photos', None)
        self.questions = kwargs.pop('questions', None)
        super(ReportQuestionSerializer, self).__init__(*args, **kwargs)

    notes = serializers.SerializerMethodField()
    answer = serializers.SerializerMethodField()

    def get_answer(self, obj):
        dict_response_answers = defaultdict(list)
        for x in self.answers:
            dict_response_answers[x.response_id].append(x)
        for response in self.responses:
            response_answers = dict_response_answers[response.id]
            for answer in [x for x in response_answers
                           if x.question_id is obj.id]:
                return answer.body

    def get_notes(self, obj):
        key_choices = obj.key_choices.split(";")
        notes = []

        dict_response_answers = defaultdict(list)
        for x in self.answers:
            dict_response_answers[x.response_id].append(x)

        for response in self.responses:
            response_answers = dict_response_answers[response.id]

            keys = [{"name": question.text, "answer": answer.body}
                    for question in self.questions
                    for answer in [x for x in response_answers
                                   if x.question_id is question.id]
                    ]

            for k in self.photos:
                keys.append({"name": "image", "keys": k.file.url})

            for answer in [x for x in response_answers
                           if x.question_id is obj.id]:
                if answer.body in key_choices:
                    notes.append({"created": response.created, "keys": keys})

        return notes

    class Meta:
        model = models.Question
        fields = ('id', 'text', 'order', 'choices',
                  'key_choices', 'notes', 'answer')


class ReportSurveySerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        self.responses = kwargs.pop('responses', None)
        self.answers = kwargs.pop('answers', None)
        self.questions = kwargs.pop('questions', None)
        super(ReportSurveySerializer, self).__init__(*args, **kwargs)

    questions = serializers.SerializerMethodField()

    def get_questions(self, obj):
        que = [x for x in self.questions
               if (x.survey_id is obj.id) and (x.type != 'select-image')]

        dict_que = defaultdict(list)
        for x in que:
            dict_que[x.is_key].append(x)

        answers = [x for x in self.answers
                   for qu in que
                   if x.question_id is qu.id]

        resps = [x for x in self.responses
                 if x.survey_id is obj.id]

        resps_id = [x.id for x in resps]
        response_type_id = ContentType.objects.get_for_model(models.Response)
        photos = [x for x in models.Attachment.objects.filter(
            content_type_id=response_type_id,
            object_id__in=resps_id)]

        return ReportQuestionSerializer(dict_que[False],
                                        responses=resps,
                                        answers=answers,
                                        questions=dict_que[True],
                                        photos=photos,
                                        many=True).data

    class Meta:
        model = models.Survey
        fields = ('id', 'name', 'questions')


class ReportGetEntitySerializer(serializers.ModelSerializer):
    checklists = serializers.SerializerMethodField()

    def get_checklists(self, obj):
        lists = [x for x in obj.checklists.all().only('name')]

        resps = [x for x in models.Response.objects
                 .filter(survey__in=lists,
                         created__range=[obj.date_from, obj.date_to])
                 .only('created', 'survey_id')
                 ]

        answers = [x for x in models.Answer.objects
                   .filter(response__in=resps)
                   .only('body', 'question_id', 'response_id')
                   ]

        questions = [x for x in models.Question.objects
                     .filter(survey__in=lists).order_by()
                     ]

        return ReportSurveySerializer(lists,
                                      responses=resps,
                                      answers=answers,
                                      questions=questions,
                                      many=True).data

    class Meta:
        model = models.Report
        fields = ('id', 'name', 'date_from', 'date_to', 'checklists')

# End report generation
