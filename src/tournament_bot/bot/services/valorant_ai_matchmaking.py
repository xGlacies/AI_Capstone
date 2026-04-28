import asyncio
import json
import requests
from openai import OpenAI

from tournament_bot.config import settings
from tournament_bot.models.dbc_model import Tournament_DB, Game


class ValorantAIMatchmakingService:
    def __init__(self):
        if not settings.OPEN_AI_KEY:
            raise ValueError("OPEN_AI_KEY is missing from your .env file.")

        self.client = OpenAI(api_key=settings.OPEN_AI_KEY)

    async def run_matchmaking(self, players_per_game: int = 10) -> dict:
        db = Tournament_DB()

        try:
            players = await self._get_registered_players_with_riot_data(db)

            if len(players) < players_per_game:
                raise ValueError(
                    f"Not enough registered players. Need {players_per_game}, found {len(players)}."
                )

            selected_players = players[:players_per_game]

            ai_result = await asyncio.to_thread(
                self._ask_chatgpt_to_balance_teams,
                selected_players
            )

            return {
                "players": selected_players,
                "ai_result": ai_result,
            }

        finally:
            db.close_db()

    async def _get_registered_players_with_riot_data(self, db: Tournament_DB) -> list[dict]:
        """
        Uses the same registered-player source as run_matchmaking:
        player table joined with latest game table row.
        Also refreshes Riot API data using game_name + tag_id.
        """

        db.cursor.execute("""
            SELECT 
                p.user_id,
                p.game_name,
                p.tag_id,
                g.tier,
                g.rank,
                g.role,
                g.wins,
                g.losses,
                g.wr,
                g.manual_tier
            FROM player p
            LEFT JOIN game g ON p.user_id = g.user_id
            WHERE g.game_date IS NULL OR g.game_date = (
                SELECT MAX(g2.game_date)
                FROM game g2
                WHERE g2.user_id = p.user_id
            )
            GROUP BY p.user_id
        """)

        records = db.cursor.fetchall()
        players = []

        for record in records:
            user_id, game_name, tag_id, tier, rank, role_json, wins, losses, wr, manual_tier = record

            riot_rank_data = await self._fetch_riot_rank_data(game_name, tag_id)

            if riot_rank_data:
                tier = riot_rank_data.get("tier", tier)
                rank = riot_rank_data.get("rank", rank)
                wins = riot_rank_data.get("wins", wins)
                losses = riot_rank_data.get("losses", losses)

                game_db = Game(db_name=settings.DATABASE_NAME)
                game_db.connection = db.connection
                game_db.cursor = db.cursor
                game_db.update_player_API_info(user_id, tier, rank, wins, losses)

            roles = self._parse_roles(role_json)

            players.append({
                "user_id": user_id,
                "game_name": game_name,
                "tag_id": tag_id,
                "tier": str(tier or "default").lower(),
                "rank": rank or "V",
                "role": roles,
                "wins": wins or 0,
                "losses": losses or 0,
                "wr": float(wr) * 100 if wr is not None else 50.0,
                "manual_tier": manual_tier,
            })

        players.sort(key=self._sort_key)
        return players

    async def _fetch_riot_rank_data(self, game_name: str, tag_id: str) -> dict | None:
        """
        Refreshes Riot data using the same Riot ID pattern already used by your project.

        Note:
        This returns League ranked data from Riot's public API flow.
        Riot does not expose normal Valorant ranked stats through this same public endpoint.
        """

        if not settings.API_KEY:
            return None

        if not game_name or not tag_id:
            return None

        return await asyncio.to_thread(self._fetch_riot_rank_data_sync, game_name, tag_id)

    def _fetch_riot_rank_data_sync(self, game_name: str, tag_id: str) -> dict | None:
        headers = {"X-Riot-Token": settings.API_KEY}

        account_url = (
            f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
            f"{game_name}/{tag_id}"
        )

        account_response = requests.get(account_url, headers=headers, timeout=10)

        if account_response.status_code != 200:
            return None

        account_info = account_response.json()
        puuid = account_info.get("puuid")

        if not puuid:
            return None

        summoner_url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        summoner_response = requests.get(summoner_url, headers=headers, timeout=10)

        if summoner_response.status_code != 200:
            return None

        summoner_info = summoner_response.json()
        summoner_id = summoner_info.get("id")

        if not summoner_id:
            return None

        ranked_url = f"https://na1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        ranked_response = requests.get(ranked_url, headers=headers, timeout=10)

        if ranked_response.status_code != 200:
            return None

        ranked_entries = ranked_response.json()

        for entry in ranked_entries:
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                return {
                    "tier": entry.get("tier", "default").lower(),
                    "rank": entry.get("rank", "V"),
                    "wins": entry.get("wins", 0),
                    "losses": entry.get("losses", 0),
                }

        return None

    def _ask_chatgpt_to_balance_teams(self, players: list[dict]) -> str:
        player_lines = []

        for player in players:
            roles = ", ".join(player.get("role", [])) or "flex"
            player_lines.append(
                f"- {player['game_name']}#{player['tag_id']} | "
                f"Rank: {player['tier']} {player['rank']} | "
                f"Wins: {player['wins']} | Losses: {player['losses']} | "
                f"Win Rate: {player['wr']:.1f}% | "
                f"Preferred Roles: {roles}"
            )

        prompt = f"""
Create two balanced 5-player Valorant teams from these registered players.

Use these priorities:
1. Balance overall skill/rank.
2. Balance win rate and experience.
3. Assign Valorant-style roles when possible:
   Duelist, Initiator, Controller, Sentinel, Flex.
4. Avoid stacking the strongest players on one team.
5. Give a short balance explanation.

Registered players:
{chr(10).join(player_lines)}

Return ONLY this format:

Team A:
- Player Name#Tag — Assigned Valorant Role — Reason

Team B:
- Player Name#Tag — Assigned Valorant Role — Reason

Balance Explanation:
Short explanation.
"""

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert Valorant tournament organizer and esports team balancer.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.35,
            max_tokens=900,
        )

        return response.choices[0].message.content

    def _parse_roles(self, role_json) -> list[str]:
        if not role_json:
            return []

        try:
            roles = json.loads(role_json)
            if isinstance(roles, list):
                return roles
            return [str(roles)]
        except Exception:
            return [str(role_json)]

    def _sort_key(self, player: dict):
        tier_order = {
            "challenger": 1,
            "grandmaster": 2,
            "master": 3,
            "diamond": 4,
            "emerald": 5,
            "platinum": 6,
            "gold": 7,
            "silver": 8,
            "bronze": 9,
            "iron": 10,
            "default": 11,
        }

        rank_order = {
            "I": 1,
            "II": 2,
            "III": 3,
            "IV": 4,
            "V": 5,
        }

        return (
            tier_order.get(player.get("tier", "default"), 11),
            rank_order.get(player.get("rank", "V"), 5),
            -player.get("wr", 0),
        )