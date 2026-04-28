import discord
from discord import app_commands
from discord.ext import commands

from tournament_bot.bot.services.valorant_ai_matchmaking import (
    ValorantAIMatchmakingService,
)


class ValorantAIMatchmakingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = ValorantAIMatchmakingService()

    @app_commands.command(
        name="valorant_ai_matchmaking",
        description="Create Valorant teams using registered players, Riot API data, and ChatGPT AI."
    )
    @app_commands.describe(
        players_per_game="Number of players to use. Default is 10."
    )
    async def valorant_ai_matchmaking(
        self,
        interaction: discord.Interaction,
        players_per_game: int = 10
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Sorry, you don't have required permission to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            result = await self.service.run_matchmaking(players_per_game)

            embed = discord.Embed(
                title="Valorant AI Matchmaking Results",
                description=result["ai_result"],
                color=discord.Color.red()
            )

            embed.set_footer(
                text=f"Used {len(result['players'])} registered players with Riot API refresh."
            )

            await interaction.followup.send(embed=embed)

        except ValueError as ex:
            await interaction.followup.send(
                f"Matchmaking input error: {ex}",
                ephemeral=True
            )

        except Exception as ex:
            await interaction.followup.send(
                f"Valorant AI matchmaking failed: {ex}",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(ValorantAIMatchmakingCommands(bot))