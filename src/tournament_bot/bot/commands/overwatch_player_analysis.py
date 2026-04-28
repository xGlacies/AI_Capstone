import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from tournament_bot.bot.services.overwatch_player_analysis import (
    OverwatchPlayerAnalysisService,
)


def build_overwatch_player_embeds(report_text: str):
    embeds = []

    sections = report_text.split("### ")

    for section in sections:
        section = section.strip()

        if not section:
            continue

        lines = section.split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else "No details provided."

        chunks = [body[i:i + 3900] for i in range(0, len(body), 3900)]

        for index, chunk in enumerate(chunks):
            embed_title = title if index == 0 else f"{title} continued"

            embed = discord.Embed(
                title=embed_title,
                description=chunk,
                color=discord.Color.blue()
            )

            embed.set_footer(text="Overwatch Individual Player Role Analysis")
            embeds.append(embed)

    if not embeds:
        embeds.append(
            discord.Embed(
                title="Overwatch Player Analysis",
                description=report_text[:3900],
                color=discord.Color.blue()
            )
        )

    return embeds


class OverwatchPlayerAnalysisCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.service = OverwatchPlayerAnalysisService()

    @app_commands.command(
    name="player_synergy_ow",
    description="Analyze one Overwatch player across roles."
    )
    @app_commands.describe(
        battletag="Player BattleTag, for example Player#1234",
        mode="Choose Competitive or Quickplay (default: Competitive)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Competitive", value="competitive"),
        app_commands.Choice(name="Quickplay", value="quickplay"),
    ])
    async def player_synergy_ow(
        self,
        interaction: discord.Interaction,
        battletag: str,
        mode: app_commands.Choice[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Sorry, you don't have the required permission to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False, thinking=True)

        try:
            selected_mode = mode.value if mode else "competitive"

            report_text = await asyncio.to_thread(
                self.service.analyze_player_sync,
                battletag,
                selected_mode
            )

            embeds = build_overwatch_player_embeds(report_text)

            for embed in embeds:
                await interaction.followup.send(embed=embed)

        except ValueError as ex:
            await interaction.followup.send(
                f"Overwatch player analysis error: {ex}",
                ephemeral=True
            )

        except Exception as ex:
            await interaction.followup.send(
                f"An unexpected error occurred while analyzing the player: {ex}",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(OverwatchPlayerAnalysisCommands(bot))