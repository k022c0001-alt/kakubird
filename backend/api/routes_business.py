from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONTACT_FILE = DATA_DIR / "contact_forms.json"
RESERVE_FILE = DATA_DIR / "reservations.json"


def _load_json(path: Path, fallback: List[Dict[str, Any]] | Dict[str, Any]) -> List[Dict[str, Any]] | Dict[str, Any]:
    try:
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return fallback


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


@router.get('/api/business/health')
async def business_health() -> Dict[str, Any]:
    return {
        'status': 'ok',
        'message': 'business API ready',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@router.post('/api/contact')
async def save_contact(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_json(CONTACT_FILE, [])
    items = data if isinstance(data, list) else []
    items.append({
        'submitted_at': datetime.now(timezone.utc).isoformat(),
        **payload,
    })
    _save_json(CONTACT_FILE, items)
    return {
        'status': 'ok',
        'message': 'お問い合わせを受け付けました。',
        'count': len(items),
    }


@router.post('/api/reserve')
async def save_reservation(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_json(RESERVE_FILE, [])
    items = data if isinstance(data, list) else []
    items.append({
        'created_at': datetime.now(timezone.utc).isoformat(),
        **payload,
    })
    _save_json(RESERVE_FILE, items)
    return {
        'status': 'ok',
        'message': '予約を受け付けました。',
        'count': len(items),
    }
