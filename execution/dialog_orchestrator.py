from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict


class MessageCounter:
    """Cuenta mensajes en la conversacion para detectar finalizacion."""

    FINAL_MESSAGE_THRESHOLD = 5
    FINISH_KEYWORD = "FIN"

    def __init__(self):
        self.count = 0
        self.finished = False
        self.messages = []

    def increment(self, sender_id: str, body: str) -> int:
        """Incrementa el contador y guarda el mensaje."""
        self.count += 1
        self.messages.append({
            'number': self.count,
            'sender': sender_id,
            'body': body,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        return self.count

    def should_finalize(self) -> bool:
        return self.count >= self.FINAL_MESSAGE_THRESHOLD

    @staticmethod
    def is_finish_signal(message_body: str) -> bool:
        return message_body.strip().upper() == MessageCounter.FINISH_KEYWORD


class DialogOrchestrator:
    """
    Orquestador de conversacion con finalizacion automatica.
    Entrega el relato final en RELATO_FINAL.md dentro del buzon de miguel.
    """

    def __init__(self, base_path: Path = None):
        self.base_path = base_path or Path.cwd()
        self.counter = MessageCounter()
        self.final_result = None
        self.conversation_log = []

    def on_message_sent(self, sender_id: str, body: str, recipient_id: str) -> Dict:
        """
        Llamado despues de cada send_message().
        Retorna dict con info sobre si se disparo finalizacion.
        """
        count = self.counter.increment(sender_id, body)
        self.conversation_log.append({
            'sender': sender_id,
            'recipient': recipient_id,
            'body': body,
            'number': count,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

        result = {
            'message_number': count,
            'is_final': False,
            'should_finalize': self.counter.should_finalize()
        }

        if self.counter.should_finalize() and self.final_result is None:
            self.final_result = {
                'sender': sender_id,
                'body': body,
                'message_number': count,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'full_conversation': self.conversation_log.copy()
            }
            self._save_final_result()
            result['is_final'] = True

        return result

    def _save_final_result(self):
        """Guarda resultado final como RELATO_FINAL.md en buzon de miguel."""
        miguel_mailbox = self.base_path / 'mailboxes' / 'miguel'
        miguel_mailbox.mkdir(parents=True, exist_ok=True)

        relato_path = miguel_mailbox / 'RELATO_FINAL.md'

        relato_lines = [
            "# Relato Final",
            "",
            f"**Mensaje #{self.final_result['message_number']}**",
            f"**De:** {self.final_result['sender']}",
            f"**Fecha:** {self.final_result['timestamp']}",
            "",
            "---",
            "",
            "## Conversacion Completa",
            ""
        ]

        for msg in self.conversation_log:
            relato_lines.append(f"**[{msg['number']}] {msg['sender']}** -> {msg['recipient']}:")
            relato_lines.append(f"{msg['body']}")
            relato_lines.append("")

        relato_lines.extend([
            "---",
            "",
            "## Texto Final (Ultimo Mensaje)",
            "",
            self.final_result['body'],
            "",
            f"*Generado: {datetime.now(timezone.utc).isoformat()}*"
        ])

        with open(relato_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(relato_lines))

        print(f"[SYSTEM] RELATO_FINAL.md guardado en {relato_path}")

    def get_conversation_summary(self) -> Dict:
        """Retorna resumen de la conversacion."""
        return {
            'total_messages': self.counter.count,
            'is_finished': self.final_result is not None,
            'messages': self.conversation_log,
            'final_text': self.final_result['body'] if self.final_result else None
        }

    def get_relato_path(self) -> Path:
        """Retorna path al RELATO_FINAL.md."""
        return self.base_path / 'mailboxes' / 'miguel' / 'RELATO_FINAL.md'

    def reset(self):
        """Reinicia el orquestador para una nueva conversacion."""
        self.counter = MessageCounter()
        self.final_result = None
        self.conversation_log = []