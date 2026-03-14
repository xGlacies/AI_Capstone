import discord, asyncio
from discord import app_commands
from discord.ext import commands
from config import settings
from model.dbc_model import Tournament_DB, Player, Game

logger = settings.logging.getLogger("discord")


class Admin_commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="allcommands", description="List all registered slash commands")
    async def listcommands(self, interaction: discord.Interaction):
        lines = []

        for cmd in self.bot.tree.walk_commands():
            if getattr(cmd, "parent", None):
                full_name = f"{cmd.parent.name} {cmd.name}"
            else:
                full_name = cmd.name
            lines.append(f"/{full_name}")

        lines = sorted(set(lines))
        text = "\n".join(lines) if lines else "No slash commands found."

        await interaction.response.send_message(f"```\n{text}\n```", ephemeral=True)

    # This file has been refactored with commands moved to:
    # - checkin_controller.py (checkin_game)
    # - player_management.py (list_players, player_match_history, simulate_checkins)
    # - matchmaking_controller.py (simulate_volunteers, run_matchmaking)
    # - match_results_controller.py (record_match_results, record_match_result)
    # - tier_management.py (view_player_tier, adjust_player_tier, reset_player_tier)


async def setup(bot):
    await bot.add_cog(Admin_commands(bot))

