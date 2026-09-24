import unittest
import json
from unittest.mock import patch, MagicMock
from src.notification_sender.dingtalk_sender import DingtalkSender
from src.config import Config

class TestDingtalkSender(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.dingtalk_webhook_url = "https://oapi.dingtalk.com/robot/send?access_token=test_token"
        self.config.dingtalk_secret = "test_secret"
        self.sender = DingtalkSender(self.config)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content", "Test Title")
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        called_url = mock_post.call_args[0][0]
        self.assertIn("timestamp=", called_url)
        self.assertIn("sign=", called_url)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_chunked_long_chinese_message_payload_size(self, mock_post):
        """Long multi-byte Chinese text and a long title beyond the 20KB limit: the JSON payload actually sent must respect the byte limit"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        # Build very long Chinese content (3 bytes per character, about 30,000 bytes of text)
        long_chinese_content = "股票复盘" * 2500 
        # Build an extremely long title
        long_title = "这是一个用来测试钉钉机器人极端边界情况的超长超长超长超长标题" * 10 

        result = self.sender.send_to_dingtalk(long_chinese_content, long_title)
        
        self.assertTrue(result)
        # It should be split into at least 2 requests
        self.assertGreaterEqual(mock_post.call_count, 2)
        
        # Check that each request's serialised JSON stays strictly under DingTalk's 20000-byte limit
        for call in mock_post.call_args_list:
            payload = call.kwargs['json']
        # Mimic the JSON serialisation used on the wire (no spaces, UTF-8)
            payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            
        # Assert the whole JSON request body finally sent is <= 20000 bytes
            self.assertLessEqual(payload_bytes, 20000, f"Payload 字节数为 {payload_bytes}，超过钉钉 20KB 限制！")
            
        # Make sure the title was truncated without losing the pagination marker
            self.assertLessEqual(len(payload['markdown']['title']), 120)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 310000, "errmsg": "invalid token"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_exception(self, mock_post):
        mock_post.side_effect = Exception("Network Error")
        result = self.sender.send_to_dingtalk("Test content")
        self.assertFalse(result)

    @patch("src.notification_sender.dingtalk_sender.requests.post")
    def test_send_strips_hidden_market_region_metadata(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"errcode": 0, "errmsg": "ok"}
        mock_post.return_value = mock_response

        result = self.sender.send_to_dingtalk("[dsa-market-region]: # (cn)\n\n# 🎯 Market Review\n\nBody")

        self.assertTrue(result)
        payload = mock_post.call_args.kwargs["json"]
        self.assertNotIn("[dsa-market-region]", payload["markdown"]["text"])
        self.assertIn("# 🎯 Market Review", payload["markdown"]["text"])
        self.assertIn("Body", payload["markdown"]["text"])
