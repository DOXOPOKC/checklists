from rest_framework import serializers
from . import models
from user_profile import models as umodels


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Question
        fields = ('id', 'text', 'order', 'required', 'type', 'choices')


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


class ReportGetSerializer(serializers.ModelSerializer):
    checklists = SurveySerializer(many=True)

    class Meta:
        model = models.Report
        fields = ('id', 'name', 'date_from', 'date_to', 'checklists')


class ResponseListSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Response
        fields = ('id', 'created', 'updated', 'survey', 'user')


class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Answer
        fields = ('id', 'question', 'body')


class ResponseSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True)

    class Meta:
        model = models.Response
        fields = ('id', 'created', 'updated', 'survey', 'user', 'interview_uuid', "answers")


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = umodels.UserProfile
        fields = ('id', 'email', 'first_name', 'last_name', 'position')
