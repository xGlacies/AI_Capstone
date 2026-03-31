import asyncio

from tournament_bot.config import settings
from tournament_bot.core.cache import Details_Cached

from tournament_bot.bot.package_loader import load_package_commands


logger = settings.logging.getLogger("discord")


def register_events(sys_client):
    @sys_client.tree.error
    async def on_app_command_error(interaction, error):
        if not sys_client.is_fully_initialized:
            try:
                await interaction.response.send_message(
                    "⏳ Bot is still initializing. Please wait about 30 seconds and try again.",
                    ephemeral=True
                )
                return
            except Exception:
                pass

        logger.error(f"Command error: {error}")
        try:
            await interaction.response.send_message(
                "An error occurred while executing the command. Please try again in a moment.",
                ephemeral=True
            )
        except Exception:
            pass

    @sys_client.event
    async def on_ready():
        logger.info(f"Logged into server as {sys_client.user}")
        logger.info("Bot is starting initialization...")

        start_time = asyncio.get_event_loop().time()

        try:
            for guild in sys_client.guilds:
                logger.info(f"Initializing guild: {guild.id} ({guild.name})")

                logger.info(f"Available roles in guild {guild.name}:")
                for role in guild.roles:
                    logger.info(f"  - Role: {role.name} (ID: {role.id})")

                await Details_Cached.channels_for_tournament(
                    ch_config=settings.CHANNEL_CONFIG,
                    guild=guild
                )

            await load_package_commands(sys_client)

            guild = sys_client.get_guild(settings.GUILD_ID)

            sys_client.tree.copy_global_to(guild=guild)
            await sys_client.tree.sync(guild=guild)

            sys_client.is_fully_initialized = True

            end_time = asyncio.get_event_loop().time()
            init_time = end_time - start_time
            logger.info(f"Bot fully initialized in {init_time:.2f} seconds!")

        except Exception as ex:
            logger.error(f"Error during initialization: {ex}")
            sys_client.is_fully_initialized = True

    @sys_client.event
    async def on_command_error(ctx, error):
        if isinstance(error, errors.ArgumentParsingError):
            await ctx.send("there is parsing error")
        if isinstance(error, errors.CommandNotFound):
            await ctx.send("Invalid command from global error handler")
        elif isinstance(error, errors.MissingRequiredArgument):
            await ctx.send("Please pass the required arguments from global error handler")
        elif isinstance(error, errors.BadArgument):
            await ctx.send("Please pass the correct arguments from global error handler")
        elif isinstance(error, errors.CommandOnCooldown):
            await ctx.send("This command is on cooldown, please try again later from global error handler")
        else:
            await ctx.send("Something went wrong, from global error handler")