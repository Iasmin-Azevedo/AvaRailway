"""Datas de aplicação de prova no fuso de Brasília."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")


def hoje_br() -> date:
    return datetime.now(TZ_BR).date()


def data_calendario_br(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(TZ_BR).date()
        return value.date()
    return value


def parse_data_aplicacao_form(data_raw: str | None) -> datetime | None:
    """Interpreta campo date (YYYY-MM-DD) como início do dia em America/Sao_Paulo."""
    raw = (data_raw or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            d = date.fromisoformat(raw)
            return datetime(d.year, d.month, d.day, tzinfo=TZ_BR)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TZ_BR)
        return dt.astimezone(TZ_BR)
    except ValueError:
        return None


def aplicacao_liberada_por_data(data_aplicacao: datetime | None, *, respondeu: bool = False) -> bool:
    if respondeu:
        return True
    if not data_aplicacao:
        return True
    data_lib = data_calendario_br(data_aplicacao)
    if data_lib is None:
        return True
    return data_lib <= hoje_br()


def aplicacao_agendada_futura(data_aplicacao: datetime | None, *, respondeu: bool = False) -> bool:
    if respondeu or not data_aplicacao:
        return False
    data_lib = data_calendario_br(data_aplicacao)
    if data_lib is None:
        return False
    return data_lib > hoje_br()
