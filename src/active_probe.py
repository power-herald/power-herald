# src/active_probe.py
import asyncio
import logging
import signal
from aiohttp import web
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, PowerStateChange, StateChangeType, Base
import datetime
from src.config import get_config
from src.outage_periods import record_outage_transition

config = get_config()
engine = create_engine(config.db_url)
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
        record_outage_transition(session, source.id, state_enum, state_change.timestamp)
        session.commit()
        logging.info(f"Active state changed for {source.name}: {state_enum.value}")
        try:
            import asyncio
            from src.notify import notify_state_change
            asyncio.create_task(notify_state_change(state_change.source_id, state_change.state, state_change.timestamp))
        except Exception as e:
            logging.warning(f"Notification failed: {e}")
    session.close()
    return web.json_response({"status": "ok"})

def create_app():
    app = web.Application()
    app.router.add_post("/active_ping", handle_active_ping)
    return app

async def main():
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    try:
        await site.start()
        logging.info("Active probe started on port 8081")
        await stop_event.wait()
        logging.info("Shutdown signal received")
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
