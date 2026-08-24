# src/active_probe.py
import logging
from aiohttp import web
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, PowerStateChange, StateChangeType, Base
import datetime

# Placeholder DB URL, replace with config
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

async def handle_active_ping(request):
    data = await request.json()
    source_name = data.get("name")
    state = data.get("state")  # 'online', 'offline', 'unstable'
    session = Session()
    source = session.query(PowerSource).filter_by(name=source_name, type=PowerSourceType.ACTIVE, enabled=True).first()
    from src.maintenance import is_maintenance
    maintenance, _ = is_maintenance(source.id if source else None)
    if maintenance:
        session.close()
        return web.json_response({"error": "Maintenance mode enabled"}, status=403)
    if not source:
        session.close()
        return web.json_response({"error": "Source not found or not active"}, status=404)
    try:
        state_enum = StateChangeType(state)
    except Exception:
        session.close()
        return web.json_response({"error": "Invalid state"}, status=400)
    last_state = session.query(PowerStateChange).filter_by(source_id=source.id).order_by(PowerStateChange.timestamp.desc()).first()
    if not last_state or last_state.state != state_enum:
        state_change = PowerStateChange(source_id=source.id, state=state_enum, timestamp=datetime.datetime.utcnow())
        session.add(state_change)
        session.commit()
        logging.info(f"Active state changed for {source.name}: {state_enum.value}")
        try:
            import asyncio
            from src.notify import notify_state_change
            asyncio.create_task(notify_state_change(state_change))
        except Exception as e:
            logging.warning(f"Notification failed: {e}")
    session.close()
    return web.json_response({"status": "ok"})

def create_app():
    app = web.Application()
    app.router.add_post("/active_ping", handle_active_ping)
    return app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, port=8081)
