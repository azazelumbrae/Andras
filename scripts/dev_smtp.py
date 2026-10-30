"""Servidor SMTP de depuración: guarda cada correo en data/mail/ y no exige auth."""

from __future__ import annotations

import asyncio
import pathlib
import time

from aiosmtpd.controller import Controller

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "mail"


class Sink:
    async def handle_DATA(self, server, session, envelope):
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (OUT / f"{stamp}-{envelope.rcpt_tos[0].replace('@', '_at_')}.eml").write_bytes(
            envelope.original_content or b"")
        print(f"[smtp] {envelope.mail_from} -> {envelope.rcpt_tos}")
        return "250 OK"


if __name__ == "__main__":
    controller = Controller(Sink(), hostname="127.0.0.1", port=1025)
    controller.start()
    print("SMTP de depuración en 127.0.0.1:1025 · salida en data/mail/")
    try:
        asyncio.run(asyncio.Event().wait())
    except KeyboardInterrupt:
        controller.stop()
