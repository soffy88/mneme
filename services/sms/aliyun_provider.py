"""
阿里云短信 Provider (代码框架，默认不启用)
==========================================
启用前提：完成阿里云短信服务签名+模板报备。
启用方式：设置环境变量 SMS_PROVIDER=aliyun 并填写以下环境变量：
  ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET
  SMS_SIGN_NAME       — 已报备的短信签名
  SMS_TEMPLATE_CODE   — 已报备的短信模板CODE（含 ${code} 变量）
"""
from __future__ import annotations

import logging
from services.sms.base import SMSProvider

logger = logging.getLogger(__name__)


class AliyunSMSProvider(SMSProvider):
    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        sign_name: str,
        template_code: str,
    ) -> None:
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.sign_name = sign_name
        self.template_code = template_code

    async def send_code(self, phone: str, code: str) -> bool:
        # ⚠️ 需要报备后才能启用。下面是调用框架，保留注释供激活时参考。
        # from alibabacloud_dysmsapi20170525.client import Client
        # from alibabacloud_tea_openapi.models import Config
        # from alibabacloud_dysmsapi20170525.models import SendSmsRequest
        #
        # config = Config(
        #     access_key_id=self.access_key_id,
        #     access_key_secret=self.access_key_secret,
        #     endpoint="dysmsapi.aliyuncs.com",
        # )
        # client = Client(config)
        # req = SendSmsRequest(
        #     phone_numbers=phone,
        #     sign_name=self.sign_name,
        #     template_code=self.template_code,
        #     template_param=f'{{"code":"{code}"}}',
        # )
        # resp = client.send_sms(req)
        # return resp.body.code == "OK"
        raise NotImplementedError(
            "阿里云短信需完成报备后启用。当前请使用 SMS_PROVIDER=mock。"
        )
