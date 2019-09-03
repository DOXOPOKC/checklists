# -*- coding: utf-8 -*-

from django.contrib.auth.models import User
from django.db import models

from .fixed_model import FixedModel
from .survey import Survey

try:
    from django.conf import settings

    if settings.AUTH_USER_MODEL:
        user_model = settings.AUTH_USER_MODEL
    else:
        user_model = User
except (ImportError, AttributeError):
    user_model = User


class Response(FixedModel):
    """
        A Response object is a collection of questions and answers with a
        unique interview uuid.
    """

    created = models.DateTimeField("Creation date", auto_now_add=True)
    updated = models.DateTimeField("Update date", auto_now=True)
    survey = models.ForeignKey(
        Survey,
        on_delete=models.CASCADE,
        verbose_name="Survey",
        related_name="responses",
    )
    user = models.ForeignKey(
        user_model,
        on_delete=models.SET_NULL,
        verbose_name="User",
        null=True,
        blank=True,
    )
    interview_uuid = models.CharField("Interview unique identifier", max_length=36)

    class Meta(object):
        verbose_name = "Set of answers to surveys"
        verbose_name_plural = "Sets of answers to surveys"

    def __str__(self):
        msg = "Response to {} by {}".format(self.survey, self.user)
        msg += " on {}".format(self.created)
        return msg