import uuid

from django.contrib.auth.models import User
from rest_framework import serializers

from faucet.models import BrightUser


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrightUser
        fields = ['pk', 'context_id', "address", "verification_url", "verification_status"]
        read_only_fields = ['context_id']

    def create(self, validated_data):
        address = validated_data['address']
        bright_user = BrightUser.get_or_create(address)
        return bright_user
