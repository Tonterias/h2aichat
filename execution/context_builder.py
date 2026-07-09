import yaml
from pathlib import Path
from typing import List, Dict, Optional


class ContextBuilder:
    def __init__(self, mailbox_path: Path):
        self.mailbox_path = Path(mailbox_path)

    def get_recent_messages(
        self,
        participant_id: str,
        limit: int = 10,
        unread_only: bool = False
    ) -> List[Dict]:
        msg_dir = self.mailbox_path / participant_id / 'messages'
        if not msg_dir.exists():
            return []

        messages = []
        messages = []
        for f_path in sorted(msg_dir.glob('*.yaml')):
            with open(f_path, 'r', encoding='utf-8') as f:
                msg_data = yaml.safe_load(f)

            if unread_only and msg_data.get('read', False):
                continue

            messages.append(msg_data)

        return messages[-limit:]

    def format_for_prompt(self, messages: List[Dict]) -> str:
        if not messages:
            return ""
        lines = []
        for m in messages:
            sender = m.get('sender', m.get('sender_id', 'unknown'))
            body = m.get('body', '')
            lines.append(f"{sender}: {body}")
        return "\n".join(lines)

    def build_context(
        self,
        participant_id: str,
        system_instructions: str,
        user_input: str,
        max_messages: int = 10
    ) -> List[Dict[str, str]]:
        messages = self.get_recent_messages(participant_id, limit=max_messages)
        history_str = self.format_for_prompt(messages)

        return [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": f"History:\n{history_str}\n\nInput: {user_input}"}
        ]