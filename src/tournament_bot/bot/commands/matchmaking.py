import discord
import asyncio
import random
import json
import requests
#from openai import OpenAI
from discord import app_commands
from discord.ext import commands
from tournament_bot.config import settings
from tournament_bot.models.dbc_model import Tournament_DB, Game
from tournament_bot.bot.services.genetic_matchmaking import GeneticMatchMaking
from google import genai
from google.genai import types


logger = settings.logging.getLogger("discord")
gemini_key = "AIzaSyDuB8zXX4bkuJxi5YqXOC5_sB9w6lCo3p8"
client = genai.Client(api_key=gemini_key)

#client = OpenAI(
#        api_key= settings.OPEN_AI_KEY 
#    )

def get_hero_roles():
    roles_dict = {}
    try:
        response = requests.get("https://overfast-api.tekrop.fr/heroes")
        if response.status_code == 200:
            for hero in response.json():
                roles_dict[hero['key']] = hero['role']
    except Exception as e:
        print(f"Failed to fetch roles: {e}")
    return roles_dict

def extract_stat(categories, target_category_label, target_stat_label=None):
    if not categories:
        return None
    for category in categories:
        if category.get('label', '').lower() == target_category_label.lower():
            if target_stat_label is None:
                return {stat['label']: stat['value'] for stat in category.get('stats', [])}
            else:
                for stat in category.get('stats', []):
                    if stat.get('label', '').lower() == target_stat_label.lower():
                        return stat.get('value')
    return None
def build_team_report_sync(usernames):
    """
    Synchronous function that handles all the API fetching and AI generation.
    Returns a string containing the final report.
    """
    hero_roles = get_hero_roles()
    if not hero_roles:
        return "Error: Could not fetch hero role mappings from the API."

    team_data = {}

    for battletag in usernames:
        formatted_tag = battletag.replace('#', '-')
        
        # 1. Fetch summary to check privacy
        summary_url = f"https://overfast-api.tekrop.fr/players/{formatted_tag}/summary"
        summary_res = requests.get(summary_url)
        
        if summary_res.status_code != 200:
            continue
            
        summary_data = summary_res.json()
        if summary_data.get('privacy') == 'private':
            continue

        # 2. Fetch Competitive detailed stats for BOTH PC and Console
        stats_url = f"https://overfast-api.tekrop.fr/players/{formatted_tag}/stats"
        res_pc = requests.get(stats_url, params={"platform": "pc", "gamemode": "competitive"})
        res_console = requests.get(stats_url, params={"platform": "console", "gamemode": "competitive"})
        
        stats_pc = res_pc.json() if res_pc.status_code == 200 else {}
        stats_console = res_console.json() if res_console.status_code == 200 else {}

        if not stats_pc and not stats_console:
            continue

        # 3. Combine playtime 
        combined_playtimes = []
        all_heroes = set(list(stats_pc.keys()) + list(stats_console.keys()))
        
        for hero_key in all_heroes:
            role = hero_roles.get(hero_key)
            if not role:
                continue
                
            pc_cats = stats_pc.get(hero_key, [])
            console_cats = stats_console.get(hero_key, [])
            
            total_time = get_time_played(pc_cats) + get_time_played(console_cats)
            
            # Require at least 1 hour (3600 seconds) of playtime
            if total_time >= 3600:
                combined_playtimes.append({
                    "hero": hero_key,
                    "role": role,
                    "time": total_time,
                    "pc_categories": pc_cats,
                    "console_categories": console_cats
                })
        
        combined_playtimes.sort(key=lambda x: x['time'], reverse=True)
        
        top_heroes = {"tank": [], "damage": [], "support": []}
        player_extracted_data = {}

        for h in combined_playtimes:
            role = h['role']
            # Top 5 per role
            if len(top_heroes[role]) < 5:
                top_heroes[role].append(h['hero'])
                hero_data = {"role": role, "combined_time_played_seconds": h['time']}
                
                if h['pc_categories']:
                    hero_data["pc_stats"] = {
                        "win_percentage": extract_stat(h['pc_categories'], "Game", "Win Percentage") or extract_stat(h['pc_categories'], "Game", "Win Rate"),
                        "weapon_accuracy": extract_stat(h['pc_categories'], "Combat", "Weapon Accuracy"),
                        "average_stats": extract_stat(h['pc_categories'], "Average"),
                        "hero_specific_stats": extract_stat(h['pc_categories'], "Hero Specific")
                    }
                
                if h['console_categories']:
                    hero_data["console_stats"] = {
                        "win_percentage": extract_stat(h['console_categories'], "Game", "Win Percentage") or extract_stat(h['console_categories'], "Game", "Win Rate"),
                        "weapon_accuracy": extract_stat(h['console_categories'], "Combat", "Weapon Accuracy"),
                        "average_stats": extract_stat(h['console_categories'], "Average"),
                        "hero_specific_stats": extract_stat(h['console_categories'], "Hero Specific")
                    }
                    
                player_extracted_data[h['hero']] = hero_data
        
        if player_extracted_data:
            team_data[battletag] = player_extracted_data

    if not team_data:
        return "No valid, public player data could be retrieved. Make sure profiles are public and have Competitive playtime."

    # 4. Prompt AI
    ai_prompt_data = json.dumps(team_data, indent=2)
    
    system_instruction = """
    You are an expert Overwatch 2 esports coach. You have been provided with statistical data for a group of players. 
    The data includes their top 5 most played heroes per role (Tank, Damage, Support) across PC and Console in Competitive mode, including Win Percentage, Weapon Accuracy, Average Stats, and Hero Specific Stats.
    
    CRITICAL INSTRUCTION: Do NOT automatically assign the hero with the highest playtime as the Primary Hero. You must analyze the heroes provided for each player and select the best Primary and Alternative heroes based on a holistic review of:
    1. High Win Percentages.
    2. Exceptional Weapon Accuracy and high-impact Hero Specific Stats.
    3. Optimal Synergy with the other team members' strongest heroes.

    Your goal is to build the optimal team composition (Standard 5v5: 1 Tank, 2 Damage, 2 Support) using the players provided. 
    If there are fewer than 5 players, build the best partial composition possible.
    
    Format your response exactly like this:
    
    ### Player Assignments
    ** User: [Player Battletag] **
    Role Assigned: [Tank / Damage / Support]
    Primary Hero: [Hero Name]
    Alternative Hero: [Hero Name]
    Strengths: 
    * (Strength Bulletpoint 1)
    * (Strength Bulletpoint 2)
    Weaknesses: 
    * (Weakness Bulletpoint 1)
    * (Weakness Bulletpoint 2)
    *(Repeat for all players)*
    
    ### Overall Team Analysis
    Team Strengths: [Explain how the chosen heroes synergize together]
    Team Weaknesses: [Explain what enemy compositions or situations might counter this team]
    """

    user_message = f"Here is the player data. Please determine the best team composition by prioritizing win rates, accuracy, and synergy over playtime:\n\n{ai_prompt_data}"

    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview', 
            contents=user_message,
            config={"system_instruction": system_instruction}
        )
        return response.text
    except Exception as e:
        return f"Error communicating with LLM API: {e}"
def get_time_played(categories):
    t = extract_stat(categories, "Game", "Time Played")
    try:
        return int(t) if t else 0
    except ValueError:
        return 0

class MatchmakingController(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    class VolunteerSelectionView(discord.ui.View):
        def __init__(self, players, needed_count, timeout=300):
            super().__init__(timeout=timeout)
            self.players = players
            self.needed_count = needed_count
            self.selected_players = []
            self.is_complete = False

            # Add player select menu
            self._add_player_select()
            self._add_action_buttons()

        def _add_player_select(self):
            # Create a select menu with player options
            options = []
            for player in self.players[:25]:  # Discord has a 25-option limit
                player_name = player.get('game_name', str(player.get('user_id')))
                tier = player.get('tier', 'unknown').capitalize()
                rank = player.get('rank', '')

                option = discord.SelectOption(
                    label=f"{player_name}",
                    description=f"{tier} {rank}",
                    value=str(player.get('user_id')),
                    default=player.get('user_id') in [p.get('user_id') for p in self.selected_players]
                )
                options.append(option)

            # Create select menu
            select = discord.ui.Select(
                placeholder="Select players to sit out...",
                min_values=0,
                max_values=min(len(options), self.needed_count),
                options=options
            )

            # Add callback
            select.callback = self.select_callback

            # Add select to view
            self.add_item(select)

        def _add_action_buttons(self):
            # Add a "Done" button
            done_button = discord.ui.Button(
                label=f"Confirm Selection ({len(self.selected_players)}/{self.needed_count})",
                style=discord.ButtonStyle.primary,
                disabled=len(self.selected_players) != self.needed_count,
                row=1
            )
            done_button.callback = self.done_callback
            self.add_item(done_button)

            # Add a "Random" button
            random_button = discord.ui.Button(
                label="Select Randomly",
                style=discord.ButtonStyle.danger,
                row=1
            )
            random_button.callback = self.random_callback
            self.add_item(random_button)
            

        async def select_callback(self, interaction):
            # Get selected player IDs from select menu
            selected_ids = [int(value) for value in interaction.data['values']]

            # Update selected players list
            self.selected_players = [p for p in self.players if p.get('user_id') in selected_ids]

            # Clear and rebuild the view
            self.clear_items()
            self._add_player_select()
            self._add_action_buttons()

            # Update the message
            await interaction.response.edit_message(
                content=f"Select {self.needed_count} volunteers to sit out (receiving participation points).\n"
                        f"Currently selected: {len(self.selected_players)}/{self.needed_count}",
                view=self
            )

        async def done_callback(self, interaction):
            if len(self.selected_players) == self.needed_count:
                self.is_complete = True
                self.stop()

                # Create a list of selected player names
                player_names = [f"{p.get('game_name')} ({p.get('tier', '').capitalize()} {p.get('rank', '')})"
                                for p in self.selected_players]

                await interaction.response.edit_message(
                    content=f"Selection complete! {self.needed_count} volunteers will sit out and receive participation points:\n" +
                            "\n".join([f"- {name}" for name in player_names]),
                    view=None
                )
            else:
                await interaction.response.send_message(
                    f"Please select exactly {self.needed_count} players before confirming.",
                    ephemeral=True
                )

        async def random_callback(self, interaction):
            # Select players randomly
            self.selected_players = random.sample(self.players, self.needed_count)
            self.is_complete = True
            self.stop()

            # Create a list of selected player names
            player_names = [f"{p.get('game_name')} ({p.get('tier', '').capitalize()} {p.get('rank', '')})"
                            for p in self.selected_players]

            await interaction.response.edit_message(
                content=f"Randomly selected {self.needed_count} players to sit out and receive participation points:\n" +
                        "\n".join([f"- {name}" for name in player_names]),
                view=None
            )

    @app_commands.command(name="simulate_volunteers", description="Simulate volunteers for sitting out")
    @app_commands.describe(count="Number of volunteers needed")
    async def simulate_volunteers(self, interaction: discord.Interaction, count: int = 4):
        if interaction.user.guild_permissions.administrator:
            db = Tournament_DB()

            try:
                # Get all players
                db.cursor.execute("""
                    SELECT p.user_id, p.game_name, p.tag_id, g.tier, g.rank 
                    FROM player p
                    JOIN game g ON p.user_id = g.user_id
                    GROUP BY p.user_id
                    HAVING MAX(g.game_date)
                """)

                all_players = []
                for record in db.cursor.fetchall():
                    user_id, game_name, tag_id, tier, rank = record
                    all_players.append({
                        'user_id': user_id,
                        'game_name': game_name,
                        'tier': tier.lower() if tier else 'default',
                        'rank': rank if rank else ''
                    })

                if len(all_players) < count:
                    await interaction.response.send_message(
                        f"Not enough players registered. Need at least {count} players, but only have {len(all_players)}."
                    )
                    return

                # Mark some players as "volunteering"
                volunteers = random.sample(all_players, count)

                # Create a volunteer table for demo
                volunteer_embed = discord.Embed(
                    title=f"Simulated Volunteers ({count} players)",
                    color=discord.Color.green(),
                    description="These players have volunteered to sit out and receive participation points."
                )

                # Role color mapping (using League of Legends colors)
                role_colors = {
                    "top": "🟥",      # Red
                    "jungle": "🟩",   # Green
                    "mid": "🟨",      # Yellow
                    "bottom": "🟦",   # Blue
                    "support": "🟪",  # Purple
                    "tbd": "⬜",      # White/empty
                    "forced": "⬛"     # Black/forced
                }
                
                for i, player in enumerate(volunteers):
                    name = player.get('game_name')
                    tier = player.get('tier', 'unknown').capitalize()
                    rank = player.get('rank', '')
                    
                    # Try to get roles
                    db.cursor.execute(
                        "SELECT role FROM game WHERE user_id = ? ORDER BY game_date DESC LIMIT 1",
                        (player.get('user_id'),)
                    )
                    role_result = db.cursor.fetchone()
                    
                    # Format roles with colors
                    colored_roles = []
                    if role_result and role_result[0]:
                        try:
                            roles = json.loads(role_result[0])
                            if isinstance(roles, list):
                                for role in roles:
                                    role_lower = role.lower()
                                    role_emoji = role_colors.get(role_lower, "⬜")
                                    colored_roles.append(f"{role_emoji} {role.capitalize()}")
                        except:
                            pass
                    
                    role_str = '  '.join(colored_roles) if colored_roles else 'None'
                    
                    value_str = f"**Rank:** {tier} {rank}"
                    if colored_roles:
                        value_str += f"\n**Roles:** {role_str}"

                    volunteer_embed.add_field(
                        name=f"Player {i + 1}: {name}",
                        value=value_str,
                        inline=True
                    )

                # Record volunteers in database with "volunteer" status
                session_id = f"volunteer_session_{int(asyncio.get_event_loop().time())}"
                # Get the next match ID for the volunteer session
                from tournament_bot.models.dbc_model import Matches
                matches_db = Matches(db_name=settings.DATABASE_NAME)
                volunteer_match_num = matches_db.get_next_match_id()
                for player in volunteers:
                    user_id = player.get('user_id')
                    if user_id:
                        query = "INSERT INTO Matches(user_id, teamUp, teamId, match_num) VALUES(?, ?, ?, ?)"
                        db.cursor.execute(query, (user_id, "volunteer", session_id, volunteer_match_num))

                db.connection.commit()
                db.close_db()

                await interaction.response.send_message(
                    content=f"Simulated {count} volunteers for sitting out.",
                    embed=volunteer_embed
                )

            except Exception as ex:
                logger.error(f"Error simulating volunteers: {ex}")
                await interaction.response.send_message(f"Error simulating volunteers: {str(ex)}")
                db.close_db()
        else:
            await interaction.response.send_message("Sorry, you don't have required permission to use this command",
                                                  ephemeral=True)

    @app_commands.command(name="run_matchmaking", description="Run matchmaking with registered players")
    @app_commands.describe(
        players_per_game="Number of players per game (default: 10)",
        selection_method="How to select players who sit out: random, rank, or volunteer (default: random)"
    )
    async def run_matchmaking(
            self,
            interaction: discord.Interaction,
            players_per_game: int = 10,
            selection_method: str = "random"
    ):
        if interaction.user.guild_permissions.administrator:
            await interaction.response.defer(thinking=True)

            try:
                # Get all eligible players
                db = Tournament_DB()
                
                all_players = []

                try:
                    # Get all players with game data
                    db.cursor.execute("""
                        SELECT p.user_id, p.game_name, p.tag_id, g.tier, g.rank, g.role, g.wins, g.losses, g.wr, g.manual_tier
                        FROM player p
                        JOIN game g ON p.user_id = g.user_id
                        GROUP BY p.user_id
                        HAVING MAX(g.game_date)
                        ORDER BY 
                            CASE 
                                WHEN g.tier = 'challenger' THEN 1
                                WHEN g.tier = 'grandmaster' THEN 2
                                WHEN g.tier = 'master' THEN 3
                                WHEN g.tier = 'diamond' THEN 4
                                WHEN g.tier = 'emerald' THEN 5
                                WHEN g.tier = 'platinum' THEN 6
                                WHEN g.tier = 'gold' THEN 7
                                WHEN g.tier = 'silver' THEN 8
                                WHEN g.tier = 'bronze' THEN 9
                                WHEN g.tier = 'iron' THEN 10
                                ELSE 11
                            END, 
                            CASE 
                                WHEN g.rank = 'I' THEN 1
                                WHEN g.rank = 'II' THEN 2
                                WHEN g.rank = 'III' THEN 3
                                WHEN g.rank = 'IV' THEN 4
                                ELSE 5
                            END
                    """)

                    player_records = db.cursor.fetchall()

                    for record in player_records:
                        user_id, game_name, tag_id, tier, rank, role_json, wins, losses, wr, manual_tier = record

                        # Parse role preferences
                        roles = []
                        if role_json:
                            try:
                                roles = json.loads(role_json)
                                if not isinstance(roles, list):
                                    roles = [str(roles)]
                            except:
                                roles = [str(role_json)]

                        player = {
                            'user_id': user_id,
                            'game_name': game_name,
                            'tag_id': tag_id,
                            'tier': tier.lower() if tier else 'default',
                            'rank': rank if rank else 'V',
                            'role': roles,
                            'wins': wins if wins is not None else 0,
                            'losses': losses if losses is not None else 0,
                            'wr': float(wr) * 100 if wr is not None else 50.0,
                            'manual_tier': manual_tier
                        }

                        all_players.append(player)

                except Exception as ex:
                    logger.error(f"Error fetching players: {ex}")
                    await interaction.followup.send(f"Error fetching players: {str(ex)}")
                    db.close_db()
                    return

                # Calculate how many games we can run and if we need players to sit out
                total_players = len(all_players)

                if total_players < players_per_game:
                    await interaction.followup.send(
                        f"Not enough players for matchmaking. Need at least {players_per_game} players, but only have {total_players}."
                    )
                    db.close_db()
                    return

                game_count = total_players // players_per_game
                extra_players = total_players % players_per_game

                await interaction.followup.send(
                    f"Found {total_players} registered players.\n"
                    f"Can create {game_count} games with {players_per_game} players each.\n"
                    f"{extra_players} players will sit out and receive participation points."
                )

                # If we have extra players, determine who sits out
                players_to_exclude = []
                participation_players = []

                if extra_players > 0:
                    selection_method = selection_method.lower()

                    if selection_method == "rank":
                        # Use lowest ranked players
                        lowest_ranked_players = all_players[-extra_players:]
                        for player in lowest_ranked_players:
                            players_to_exclude.append(player['user_id'])
                            participation_players.append(player)

                        await interaction.followup.send(
                            f"**Using rank-based selection:** {extra_players} lowest-ranked players will sit out but receive participation points."
                        )

                    elif selection_method == "volunteer":
                        # Use interactive volunteer selection
                        await interaction.followup.send(
                            f"Please select {extra_players} volunteers to sit out (they will receive participation points)."
                        )

                        # Create volunteer selection view
                        view = self.VolunteerSelectionView(all_players, extra_players)
                        volunteer_msg = await interaction.followup.send(
                            content=f"Select {extra_players} volunteers to sit out (receiving participation points).\n"
                                    f"Currently selected: 0/{extra_players}",
                            view=view
                        )

                        # Wait for selection to complete
                        await view.wait()

                        if view.is_complete:
                            participation_players = view.selected_players
                            for player in participation_players:
                                players_to_exclude.append(player['user_id'])
                        else:
                            # Fallback to random if view timed out
                            random_players = random.sample(all_players, extra_players)
                            for player in random_players:
                                players_to_exclude.append(player['user_id'])
                                participation_players.append(player)

                            await interaction.followup.send(
                                f"Volunteer selection timed out. Falling back to random selection."
                            )

                    else:  # Default to random
                        # Randomly select players to sit out
                        random_players = random.sample(all_players, extra_players)
                        for player in random_players:
                            players_to_exclude.append(player['user_id'])
                            participation_players.append(player)

                        await interaction.followup.send(
                            f"**Using random selection:** {extra_players} randomly selected players will sit out but receive participation points."
                        )

                # Remove excluded players
                filtered_players = [p for p in all_players if p['user_id'] not in players_to_exclude]

                # Split players into pools based on skill
                filtered_players.sort(key=lambda p: (
                    {'challenger': 1, 'grandmaster': 2, 'master': 3, 'diamond': 4, 'emerald': 5,
                     'platinum': 6, 'gold': 7, 'silver': 8, 'bronze': 9, 'iron': 10}.get(p['tier'], 11),
                    {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}.get(p['rank'], 5),
                    -p.get('wr', 0)
                ))

                # Create pools for skill-based games
                pools = []
                for i in range(game_count):
                    start_idx = i * players_per_game
                    end_idx = start_idx + players_per_game
                    pool = filtered_players[start_idx:end_idx]
                    pools.append(pool)

                # Run matchmaking for each pool
                results = []
                matchmaker = GeneticMatchMaking()

                for pool_idx, pool in enumerate(pools):
                    # Get the next match ID
                    from tournament_bot.models.dbc_model import Matches
                    matches_db = Matches(db_name=settings.DATABASE_NAME)
                    match_num = matches_db.get_next_match_id()
                    match_id = f"match_{match_num}"

                    # Split pool into balanced teams
                    team1, team2 = [], []

                    # Process players with performance metrics
                    processed_players = await matchmaker.calculate_performance(pool)

                    # Run matchmaking
                    best_chromosome, best_fitness = matchmaker.genetic_algorithm(
                        processed_players,
                        population_size=100,
                        generations=100,
                        team_size=players_per_game // 2
                    )

                    if best_chromosome:
                        team1, team2 = matchmaker.decode_chromosome(
                            best_chromosome,
                            processed_players,
                            team_size=players_per_game // 2
                        )
                    else:
                        # Fallback: simple alternating assignment
                        for i, player in enumerate(pool):
                            if i % 2 == 0:
                                team1.append(player)
                            else:
                                team2.append(player)

                    # Record match in database
                    for player in team1:
                        user_id = player.get('user_id')
                        if user_id:
                            query = "INSERT INTO Matches(user_id, teamUp, teamId, match_num) VALUES(?, ?, ?, ?)"
                            db.cursor.execute(query, (user_id, "team1", match_id, match_num))

                    for player in team2:
                        user_id = player.get('user_id')
                        if user_id:
                            query = "INSERT INTO Matches(user_id, teamUp, teamId, match_num) VALUES(?, ?, ?, ?)"
                            db.cursor.execute(query, (user_id, "team2", match_id, match_num))

                    # Calculate team metrics
                    team1_perf = matchmaker.team_performance(team1)
                    team2_perf = matchmaker.team_performance(team2)
                    diff = abs(team1_perf - team2_perf)
                    
                    # Calculate role matchup score for display
                    role_matchup_score = matchmaker.calculate_role_matchup_score(team1, team2)
                    role_matchup_percent = round(role_matchup_score * 100)
                    
                    # ==========================================
                    # START OF LLM INTEGRATION: matchmaking_llm_analysis.py
                    # ==========================================
                    # Create minimal datasets to save tokens and keep the LLM focused
                    t1_minimal = [{"name": p.get("game_name"), "tier": p.get("tier"), "rank": p.get("rank"), "role": p.get("assigned_role")} for p in team1]
                    t2_minimal = [{"name": p.get("game_name"), "tier": p.get("tier"), "rank": p.get("rank"), "role": p.get("assigned_role")} for p in team2]
                    
                    # Call our new service
                    from tournament_bot.bot.services.matchmaking_llm_analysis import analyze_matchup
                    llm_insights = await analyze_matchup(t1_minimal, t2_minimal, diff)

                    # Log the insights to the database
                    try:
                        insight_query = """
                            INSERT INTO match_insights (match_id, analysis_summary, key_matchup, fairness_rating) 
                            VALUES (?, ?, ?, ?)
                        """
                        db.cursor.execute(
                            insight_query, 
                            (
                                match_id, 
                                llm_insights['analysis_summary'], 
                                llm_insights['key_matchup'], 
                                llm_insights['fairness_rating']
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to save LLM insights to database for {match_id}: {e}")
                    # ==========================================
                    # END OF LLM INTEGRATION: matchmaking_llm_analysis.py
                    # ==========================================

                    # Create embeds for the teams
                    # Create the original math/stats description
                    stats_desc = f"*(Game {pool_idx + 1} of {game_count})*\n**Role Matchup Balance:** {role_matchup_percent}%"
                    
                    # Create the AI insights description
                    ai_desc = f"**🏆 AI Match Overview:**\n{llm_insights['analysis_summary']}\n\n**⚔️ Key Matchup:** {llm_insights['key_matchup']}\n**⚖️ AI Fairness Rating:** {llm_insights['fairness_rating']}%"
                    
                    # Combine them with a clean divider
                    combined_description = f"{stats_desc}\n\n{ai_desc}"

                    # Create embeds for the teams
                    team1_embed = discord.Embed(
                        title=f"Game {pool_idx + 1} - Team 1 (Match ID: {match_id})",
                        color=discord.Color.blue(),
                        description=combined_description
                    )

                    team2_embed = discord.Embed(
                        title=f"Game {pool_idx + 1} - Team 2 (Match ID: {match_id})",
                        color=discord.Color.red(),
                        description=combined_description
                    )
                    """
                    team1_embed = discord.Embed(
                        title=f"Game {pool_idx + 1} - Team 1 (Match ID: {match_id})",
                        color=discord.Color.blue(),
                        description=f"Game {pool_idx + 1} of {game_count}\nRole Matchup Balance: {role_matchup_percent}%"
                    )

                    team2_embed = discord.Embed(
                        title=f"Game {pool_idx + 1} - Team 2 (Match ID: {match_id})",
                        color=discord.Color.red(),
                        description=f"Game {pool_idx + 1} of {game_count}\nRole Matchup Balance: {role_matchup_percent}%"
                    )
                    """
                    # Role color mapping (using League of Legends colors)
                    role_colors = {
                        "top": "🟥",      # Red
                        "jungle": "🟩",   # Green
                        "mid": "🟨",      # Yellow
                        "bottom": "🟦",   # Blue
                        "support": "🟪",  # Purple
                        "tbd": "⬜",      # White/empty
                        "forced": "⬛"     # Black/forced
                    }
                    
                    # Add players to embeds
                    for i, player in enumerate(team1):
                        name = player.get('game_name', player.get('user_id', 'Unknown'))
                        tier = player.get('tier', 'Unknown').capitalize()
                        rank = player.get('rank', '')
                        roles = player.get('role', [])
                        
                        # Format roles with colors
                        colored_roles = []
                        for role in roles:
                            role_lower = role.lower()
                            role_emoji = role_colors.get(role_lower, "⬜")
                            colored_roles.append(f"{role_emoji} {role.capitalize()}")
                        
                        role_str = '  '.join(colored_roles) if colored_roles else 'None'

                        # Use the assigned_role from genetic algorithm if available
                        if "assigned_role" in player:
                            assigned_role = player["assigned_role"]
                        else:
                            # Fallback to first role preference
                            assigned_role = roles[0] if roles else "TBD"
                            logger.warning(f"Player {name} missing assigned_role, using first preference")
                        
                        assigned_role_lower = assigned_role.lower()
                        assigned_emoji = role_colors.get(assigned_role_lower, role_colors["tbd"])
                        colored_assigned = f"{assigned_emoji} {assigned_role.capitalize()}"

                        team1_embed.add_field(
                            name=f"Player {i + 1}: {name}",
                            value=f"**Rank:** {tier} {rank}\n**Roles:** {role_str}\n**Assigned:** {colored_assigned}",
                            inline=True
                        )

                    for i, player in enumerate(team2):
                        name = player.get('game_name', player.get('user_id', 'Unknown'))
                        tier = player.get('tier', 'Unknown').capitalize()
                        rank = player.get('rank', '')
                        roles = player.get('role', [])
                        
                        # Format roles with colors
                        colored_roles = []
                        for role in roles:
                            role_lower = role.lower()
                            role_emoji = role_colors.get(role_lower, "⬜")
                            colored_roles.append(f"{role_emoji} {role.capitalize()}")
                        
                        role_str = '  '.join(colored_roles) if colored_roles else 'None'

                        # Use the assigned_role from genetic algorithm if available
                        if "assigned_role" in player:
                            assigned_role = player["assigned_role"]
                        else:
                            # Fallback to first role preference
                            assigned_role = roles[0] if roles else "TBD"
                            logger.warning(f"Player {name} missing assigned_role, using first preference")
                        
                        assigned_role_lower = assigned_role.lower()
                        assigned_emoji = role_colors.get(assigned_role_lower, role_colors["tbd"])
                        colored_assigned = f"{assigned_emoji} {assigned_role.capitalize()}"

                        team2_embed.add_field(
                            name=f"Player {i + 1}: {name}",
                            value=f"**Rank:** {tier} {rank}\n**Roles:** {role_str}\n**Assigned:** {colored_assigned}",
                            inline=True
                        )

                    # Add metrics to embeds
                    team1_embed.set_footer(text=f"Team 1 Performance: {team1_perf:.2f}")
                    team2_embed.set_footer(text=f"Team 2 Performance: {team2_perf:.2f}")

                    # Create role matchup comparison
                    standard_roles = ["top", "jungle", "mid", "bottom", "support"]
                    role_matchup_text = "**Role Matchups:**\n"
                    
                    # Get role emoji mapping
                    role_emoji_map = {
                        "top": "🟥 Top",
                        "jungle": "🟩 Jungle",
                        "mid": "🟨 Mid", 
                        "bottom": "🟦 Bottom",
                        "support": "🟪 Support"
                    }
                    
                    for role in standard_roles:
                        team1_player = next((p for p in team1 if p.get("assigned_role") == role), None)
                        team2_player = next((p for p in team2 if p.get("assigned_role") == role), None)
                        
                        if team1_player and team2_player:
                            team1_name = team1_player.get('game_name', 'Unknown')
                            team2_name = team2_player.get('game_name', 'Unknown')
                            team1_tier = team1_player.get('tier', 'default').capitalize()
                            team2_tier = team2_player.get('tier', 'default').capitalize()
                            team1_rank = team1_player.get('rank', '')
                            team2_rank = team2_player.get('rank', '')
                            
                            role_display = role_emoji_map.get(role, role.capitalize())
                            role_matchup_text += f"{role_display}: {team1_name} ({team1_tier} {team1_rank}) vs {team2_name} ({team2_tier} {team2_rank})\n"
                    
                    # Instructions for recording match outcome
                    instructions = (
                        f"**Matchmaking - Game {pool_idx + 1} of {game_count}**\n"
                        f"Match ID: `{match_id}`\n"
                        f"Team Performance Difference: {diff:.2f}\n"
                        f"Role Matchup Balance: {role_matchup_percent}%\n\n"
                        f"{role_matchup_text}\n"
                        f"To record match results, use: `/record_match_result {match_id} <winning_team>`\n"
                        f"where <winning_team> is either 1 or 2."
                    )

                    results.append({
                        "match_id": match_id,
                        "pool_idx": pool_idx,
                        "embeds": [team1_embed, team2_embed],
                        "instructions": instructions
                    })

                # Record participation points for excluded players
                if participation_players:
                    participation_id = f"participation_{int(asyncio.get_event_loop().time())}"
                    # Get the next match ID for the participation session
                    from tournament_bot.models.dbc_model import Matches
                    matches_db = Matches(db_name=settings.DATABASE_NAME)
                    participation_match_num = matches_db.get_next_match_id()
                    for player in participation_players:
                        user_id = player.get('user_id')
                        if user_id:
                            query = "INSERT INTO Matches(user_id, teamUp, teamId, match_num) VALUES(?, ?, ?, ?)"
                            db.cursor.execute(query, (user_id, "participation", participation_id, participation_match_num))

                # Commit all changes to database
                db.connection.commit()
                db.close_db()

                # Send results for each game
                for result in results:
                    await interaction.followup.send(content=result["instructions"], embeds=result["embeds"])

                # If there were participation players, show them too
                if participation_players:
                    participation_embed = discord.Embed(
                        title="Players Receiving Participation Points",
                        color=discord.Color.green(),
                        description=f"{len(participation_players)} players are sitting out but will receive participation points."
                    )

                    for i, player in enumerate(participation_players):
                        name = player.get('game_name', player.get('user_id', 'Unknown'))
                        tier = player.get('tier', 'Unknown').capitalize()
                        rank = player.get('rank', '')
                        roles = player.get('role', [])
                        
                        # Format roles with colors
                        colored_roles = []
                        for role in roles:
                            role_lower = role.lower()
                            role_emoji = role_colors.get(role_lower, "⬜")
                            colored_roles.append(f"{role_emoji} {role.capitalize()}")
                        
                        role_str = '  '.join(colored_roles) if colored_roles else 'None'

                        participation_embed.add_field(
                            name=f"Player {i + 1}: {name}",
                            value=f"**Rank:** {tier} {rank}\n**Roles:** {role_str}",
                            inline=True
                        )

                    await interaction.followup.send(embed=participation_embed)

            except Exception as ex:
                logger.error(f"Error running matchmaking: {ex}")
                await interaction.followup.send(f"Error running matchmaking: {str(ex)}")
        else:
            await interaction.response.send_message("Sorry, you don't have required permission to use this command",
                                                  ephemeral=True)

    @app_commands.command(name="team_synergy_ow", description="Generate a synergized Overwatch team comp based on player career hero stats and hero usage time")
    @app_commands.describe(usernames="Comma or space-separated BattleTags (e.g. Player#1234, Hero#5678)")
    async def analyze_team(self, interaction: discord.Interaction, usernames: str):
        # 1. Administrator Check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Sorry, you don't have the required permission to use this command.",
                ephemeral=True
            )
            return

        # 2. Defer response (This prevents the interaction from timing out while APIs are running)
        await interaction.response.defer(ephemeral=False)

        # 3. Clean and parse input
        # Replaces commas with spaces, then splits by space to handle varying input styles cleanly
        clean_input = usernames.replace(',', ' ')
        player_list = [name.strip() for name in clean_input.split() if name.strip()]

        if not player_list:
            await interaction.followup.send("Please provide valid BattleTags.")
            return

        if len(player_list) > 5:
            await interaction.followup.send("Please provide a maximum of 5 BattleTags.")
            return

        # 4. Run the blocking API calls in a separate thread so the bot doesn't freeze
        try:
            report_text = await asyncio.to_thread(build_team_report_sync, player_list)
            
            # 5. Discord 2000 Character Limit Handling
            if len(report_text) <= 2000:
                await interaction.followup.send(content=report_text)
            else:
                # Split the text into chunks of 1900 to be safe
                chunks = [report_text[i:i+1900] for i in range(0, len(report_text), 1900)]
                for i, chunk in enumerate(chunks):
                    # Send the first chunk directly to the followup, send the rest as standard channel messages
                    if i == 0:
                        await interaction.followup.send(content=chunk)
                    else:
                        await interaction.channel.send(content=chunk)

        except Exception as ex:
            await interaction.followup.send(f"An error occurred while generating the report: {str(ex)}")
        
async def setup(bot):
    await bot.add_cog(MatchmakingController(bot))


