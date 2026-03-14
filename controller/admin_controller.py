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
    # - admin_controller.py (allcommands)
    # - checkin_controller.py (checkin_game)
    # - export_import.py (export_players, import_players)
    # - match_results_controller.py (record_match_result, record_match_results)
    # - matchmaking_controller.py (run_matchmaking, simulate_volunteers)
    # - mvp_voting_controller.py (end_mvp_voting, list_active_mvp_votes, start_mvp_voting, view_mvp_results, view_player_mvps, vote_mvp)
    # - player_commands.py (playersinfo)
    # - player_management.py (get_toxicity, list_players, player_match_history, simulate_checkins, toxicity)
    # - player_signup.py (register)
    # - team_display_controller.py (announce_teams, display_teams)
    # - team_swap_controller.py (swap_team_players)
    # - tier_management.py (adjust_player_tier, reset_player_tier, view_player_tier)


async def setup(bot):
    await bot.add_cog(Admin_commands(bot))

