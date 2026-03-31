from discord.ext.commands import errors

from tournament_bot.config import settings
from tournament_bot.bot.command_registry import PACKAGE_COMMAND_MODULES


logger = settings.logging.getLogger("discord")


async def load_package_commands(sys_client):
    for module_path in PACKAGE_COMMAND_MODULES:
        try:
            await sys_client.load_extension(module_path)
            logger.info(f"Loaded package command: {module_path}")
        except errors.ExtensionAlreadyLoaded:
            logger.info(f"{module_path} is already loaded")
        except Exception as ex:
            logger.error(f"Error loading package command {module_path}: {ex}")