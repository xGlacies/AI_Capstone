import discord
import asyncio
from discord.ext import commands
from tournament_bot.config import settings
from tournament_bot.bot.bot import create_bot
from tournament_bot.core.startup import initialize_database
from tournament_bot.bot.events import register_events
from tournament_bot.core.database import tournament_dbc
import warnings
warnings.filterwarnings("ignore", message="'audioop' is deprecated")


logger = settings.logging.getLogger("discord")

async def main():
    logger.info("start bot")

    sys_client = create_bot()

    sys_client = create_bot()
    register_events(sys_client)

    # Initialize the database and create tables
    db = initialize_database()
    
    # Run the bot with your token
    try:
        await sys_client.start(settings.DISCORD_API_SECRET, reconnect=True)
    finally:
        await sys_client.close()

if __name__ == "__main__":
    asyncio.run(main())