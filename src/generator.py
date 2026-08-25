# src/generator.py
import logging
from aiohttp import web
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, StateChangeType
from src.notify import notify_state_change
from src.state_store import latest_state, record_change, record_state
import asyncio
import datetime

logger = logging.getLogger(__name__)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

async def handle_generator_command(request):
    """Handle generator start/stop commands
    POST body: {"source_name": "Generator_1", "command": "start"|"stop"}
    """
    data = await request.json()
    source_name = data.get("source_name")
    command = data.get("command")  # 'start' or 'stop'
    
    if command not in ["start", "stop"]:
        return web.json_response({"error": "Invalid command"}, status=400)
    
    session = Session()
    source = session.query(PowerSource).filter_by(name=source_name, type=PowerSourceType.GENERATOR, enabled=True).first()
    if not source:
        session.close()
        return web.json_response({"error": "Generator source not found"}, status=404)
    
    new_state = StateChangeType.ONLINE if command == "start" else StateChangeType.OFFLINE
    last_state = latest_state(session, source.id, stable_only=True)
    
    if not last_state or last_state.state != new_state:
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        record_state(session, source.id, new_state, timestamp)
        record_change(session, source.id, new_state, timestamp)
        session.commit()
        logger.info("Generator %s command: %s", source.name, command)
        
        # Trigger notifications
        try:
            asyncio.create_task(notify_state_change(source.id, new_state, timestamp))
        except Exception as e:
            logger.warning("Notification failed: %s", e)
    
    session.close()
    return web.json_response({"status": "ok"})

def create_app():
    app = web.Application()
    app.router.add_post("/generator", handle_generator_command)
    return app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    web.run_app(app, port=8082)
