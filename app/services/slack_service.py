import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackService:
    def __init__(self):
        token = os.getenv("SLACK_BOT_TOKEN")
        self.client = WebClient(token=token) if token else None

    def send_message(self, channel: str, text: str):
        if not self.client:
            return {"message": "Slack not configured."}

        try:
            response = self.client.chat_postMessage(channel=channel, text=text)
            return {"message": "Slack message sent.", "ts": response["ts"]}
        except SlackApiError as e:
            return {"message": f"Slack error: {e.response['error']}"}