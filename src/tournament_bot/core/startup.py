from tournament_bot.models.dbc_model import (
    Tournament_DB,
    Player,
    Game,
    Matches,
    MVP_Votes,
    Player_game_info,
    Match_Insights,
)


def initialize_database() -> Tournament_DB:
    db = Tournament_DB()
    Player.createTable(db)
    Game.createTable(db)
    Matches.createTable(db)
    MVP_Votes.createTable(db)
    Player_game_info.createTable(db)
    Match_Insights.createTable(db)
    return db
