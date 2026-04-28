PACKAGE_COMMAND_MODULES = [
    # Core commands
    "tournament_bot.bot.commands.player",
    "tournament_bot.bot.commands.signup",
    "tournament_bot.bot.commands.tier_management",
    "tournament_bot.bot.commands.checkin",
    "tournament_bot.bot.commands.results",
    "tournament_bot.bot.commands.mvp_voting",

    # Additional commands
    "tournament_bot.bot.commands.giveaway",
    "tournament_bot.bot.commands.team_swap",
    "tournament_bot.bot.commands.team",
    "tournament_bot.bot.commands.admin",
    "tournament_bot.bot.commands.export_import",
    "tournament_bot.bot.commands.player_management",

    # Matchmaking system
    "tournament_bot.bot.commands.matchmaking",
    "tournament_bot.bot.commands.matchmaking_test",
    "tournament_bot.bot.commands.valorant_ai_matchmaking",
    "tournament_bot.bot.commands.overwatch_player_analysis",

    # Utility / test command
    "tournament_bot.bot.commands.role_assignment_test",

    # Event listeners
    "tournament_bot.bot.listeners.member_events",

    # Riot API
    "tournament_bot.bot.services.api",
]