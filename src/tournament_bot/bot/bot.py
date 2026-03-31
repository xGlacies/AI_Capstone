import discord
from discord.ext import commands

def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    sys_client = commands.Bot(command_prefix="$", intents=intents)

    # Track whether startup initialization is finished
    sys_client.is_fully_initialized = False

    return sys_client