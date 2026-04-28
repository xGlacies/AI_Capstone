import json
import requests
from google import genai

from tournament_bot.config import settings


client = genai.Client(api_key=settings.GEMINI_API_KEY)


def extract_stat(categories, target_category_label, target_stat_label=None):
    if not categories:
        return None

    for category in categories:
        if category.get("label", "").lower() == target_category_label.lower():
            if target_stat_label is None:
                return {
                    stat["label"]: stat["value"]
                    for stat in category.get("stats", [])
                }

            for stat in category.get("stats", []):
                if stat.get("label", "").lower() == target_stat_label.lower():
                    return stat.get("value")

    return None


def get_time_played(categories):
    time_played = extract_stat(categories, "Game", "Time Played")

    try:
        return int(time_played) if time_played else 0
    except ValueError:
        return 0


class OverwatchPlayerAnalysisService:
    def get_hero_roles(self):
        roles = {}

        response = requests.get(
            "https://overfast-api.tekrop.fr/heroes",
            timeout=15
        )

        if response.status_code != 200:
            raise ValueError("Could not fetch Overwatch hero role data.")

        for hero in response.json():
            roles[hero["key"]] = hero["role"]

        return roles

    def analyze_player_sync(self, battletag: str) -> str:
        formatted_tag = battletag.replace("#", "-")

        hero_roles = self.get_hero_roles()

        summary_url = f"https://overfast-api.tekrop.fr/players/{formatted_tag}/summary"
        summary_response = requests.get(summary_url, timeout=15)

        if summary_response.status_code != 200:
            raise ValueError(
                "Player profile was not found. Check the BattleTag spelling and casing."
            )

        summary_data = summary_response.json()

        if summary_data.get("privacy") == "private":
            raise ValueError(
                "This player profile is private. The Overwatch profile must be public."
            )

        stats_url = f"https://overfast-api.tekrop.fr/players/{formatted_tag}/stats"

        pc_response = requests.get(
            stats_url,
            params={"platform": "pc", "gamemode": "quickplay"},
            timeout=20
        )

        console_response = requests.get(
            stats_url,
            params={"platform": "console", "gamemode": "quickplay"},
            timeout=20
        )

        stats_pc = pc_response.json() if pc_response.status_code == 200 else {}
        stats_console = console_response.json() if console_response.status_code == 200 else {}

        if not stats_pc and not stats_console:
            raise ValueError("No competitive stats were found for this player.")

        player_data = self._build_player_role_data(
            stats_pc=stats_pc,
            stats_console=stats_console,
            hero_roles=hero_roles
        )

        if not player_data:
            raise ValueError(
                "Not enough competitive playtime found. The player needs at least 1 hour on a hero."
            )

        return self._ask_ai_for_player_role_analysis(
            battletag=battletag,
            player_data=player_data
        )

    def _build_player_role_data(self, stats_pc, stats_console, hero_roles):
        all_heroes = set(list(stats_pc.keys()) + list(stats_console.keys()))

        role_data = {
            "tank": [],
            "damage": [],
            "support": [],
        }

        for hero_key in all_heroes:
            role = hero_roles.get(hero_key)

            if role not in role_data:
                continue

            pc_categories = stats_pc.get(hero_key, [])
            console_categories = stats_console.get(hero_key, [])

            total_time = get_time_played(pc_categories) + get_time_played(console_categories)

            # Require at least 1 hour on the hero
            if total_time < 3600:
                continue

            hero_data = {
                "hero": hero_key,
                "role": role,
                "combined_time_played_seconds": total_time,
            }

            if pc_categories:
                hero_data["pc_stats"] = {
                    "win_percentage": extract_stat(pc_categories, "Game", "Win Percentage")
                    or extract_stat(pc_categories, "Game", "Win Rate"),
                    "weapon_accuracy": extract_stat(pc_categories, "Combat", "Weapon Accuracy"),
                    "average_stats": extract_stat(pc_categories, "Average"),
                    "hero_specific_stats": extract_stat(pc_categories, "Hero Specific"),
                }

            if console_categories:
                hero_data["console_stats"] = {
                    "win_percentage": extract_stat(console_categories, "Game", "Win Percentage")
                    or extract_stat(console_categories, "Game", "Win Rate"),
                    "weapon_accuracy": extract_stat(console_categories, "Combat", "Weapon Accuracy"),
                    "average_stats": extract_stat(console_categories, "Average"),
                    "hero_specific_stats": extract_stat(console_categories, "Hero Specific"),
                }

            role_data[role].append(hero_data)

        for role in role_data:
            role_data[role].sort(
                key=lambda hero: hero["combined_time_played_seconds"],
                reverse=True
            )

            # Keep only top 5 heroes per role so the AI prompt does not get too large
            role_data[role] = role_data[role][:5]

        return {
            role: heroes
            for role, heroes in role_data.items()
            if heroes
        }

    def _ask_ai_for_player_role_analysis(self, battletag: str, player_data: dict) -> str:
        ai_prompt_data = json.dumps(player_data, indent=2)

        system_instruction = """
You are an expert Overwatch 2 esports coach.

Analyze one player's competitive Overwatch data across each role:
Tank, Damage, and Support.

Important:
- Do not only choose the hero with the most playtime.
- Consider win percentage, weapon accuracy, average stats, hero-specific stats, and total experience.
- Explain which roles the player is strongest in and why.
- If the player has no valid data for a role, say that there was not enough data for that role.
- Use markdown section headers beginning with ### so Discord can split the response into embeds.

Return the response exactly in this format:

### Player Summary
Player: [BattleTag]
Best Overall Role: [Tank / Damage / Support / Flex]
Short Summary: [Brief explanation]

### Tank Analysis
Best Tank Hero: [Hero Name or Not Enough Data]
Alternative Tank Hero: [Hero Name or None]
Strengths:
* [Strength]
* [Strength]
Weaknesses:
* [Weakness]
* [Weakness]
Role Fit Score: [1-10]

### Damage Analysis
Best Damage Hero: [Hero Name or Not Enough Data]
Alternative Damage Hero: [Hero Name or None]
Strengths:
* [Strength]
* [Strength]
Weaknesses:
* [Weakness]
* [Weakness]
Role Fit Score: [1-10]

### Support Analysis
Best Support Hero: [Hero Name or Not Enough Data]
Alternative Support Hero: [Hero Name or None]
Strengths:
* [Strength]
* [Strength]
Weaknesses:
* [Weakness]
* [Weakness]
Role Fit Score: [1-10]

### Final Recommendation
Recommended Role: [Tank / Damage / Support / Flex]
Recommended Hero Pool: [Hero 1, Hero 2, Hero 3]
Coaching Advice:
* [Advice]
* [Advice]
"""

        user_message = f"""
Analyze this Overwatch player:

Player: {battletag}

Competitive hero data:
{ai_prompt_data}
"""

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=user_message,
            config={"system_instruction": system_instruction}
        )

        return response.text