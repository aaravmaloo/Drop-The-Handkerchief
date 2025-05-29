import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
import os # Import the os module
from dotenv import load_dotenv # Import load_dotenv

# --- Load Environment Variables ---
load_dotenv('auth.env') # Load variables from secret.env


# --- Configuration ---

BOT_TOKEN = os.getenv("DISCORD_TOKEN") # Get the token from the environment variable

SCORE_FILE = "scores.json"
POINTS_PER_DUEL_WIN = 10
RESPONSE_TIMEOUT = 30.0
MAX_NUMBER = 60
MAX_SCORE_DISPLAY = 300

# --- Global State ---
# ... (rest of your global variables: scores_data, active_duels, GLOBAL_GAME_ROUND)
scores_data = {}
active_duels = {}
GLOBAL_GAME_ROUND = 0


# --- Intents Setup ---
# ... (rest of your intents setup)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Helper Classes (DMInteractionError, etc. - keep as they are) ---
class DMInteractionError(Exception):
    def __init__(self, player, message="DM interaction failed."):
        self.player = player
        self.message = message
        super().__init__(self.message)


# ... (DMDisabledError, DMHttpError, PlayerTimedOutError - keep these)
class DMDisabledError(DMInteractionError):
    def __init__(self, player):
        super().__init__(player, f"DM disabled for {player.mention}.")


class DMHttpError(DMInteractionError):
    def __init__(self, player, original_exception):
        super().__init__(player, f"HTTP error sending DM to {player.mention}: {original_exception}")
        self.original_exception = original_exception


class PlayerTimedOutError(DMInteractionError):
    def __init__(self, player):
        super().__init__(player, f"Player {player.mention} timed out.")


# --- Score Management (NEW STRUCTURE) ---
def load_scores():
    global scores_data
    try:
        with open(SCORE_FILE, 'r') as f:
            loaded_json = json.load(f)
            # Convert string guild_ids and user_ids from JSON keys back to int if necessary
            # For simplicity, we'll assume they are stored as strings, which is common for JSON keys
            scores_data = loaded_json
    except FileNotFoundError:
        scores_data = {}
        print(f"Info: {SCORE_FILE} not found. Starting with empty scores data.")
    except json.JSONDecodeError:
        print(f"Warning: {SCORE_FILE} is corrupted. Starting with empty scores data.")
        scores_data = {}


def save_scores():
    with open(SCORE_FILE, 'w') as f:
        json.dump(scores_data, f, indent=4)


def get_player_stats(guild_id: int, user_id: int):
    """Gets a player's stats for a specific guild, or returns default stats."""
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)
    if guild_id_str in scores_data and user_id_str in scores_data[guild_id_str]:
        return scores_data[guild_id_str][user_id_str]
    return {
        "username": "Unknown User",  # Will be updated on first game
        "points": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "games_played": 0
    }


def update_player_stats(guild_id: int, user: discord.User, outcome: str, points_change: int):
    """
    Updates player stats after a game.
    outcome can be "win", "loss", "tie".
    """
    guild_id_str = str(guild_id)
    user_id_str = str(user.id)

    if guild_id_str not in scores_data:
        scores_data[guild_id_str] = {}

    if user_id_str not in scores_data[guild_id_str]:
        scores_data[guild_id_str][user_id_str] = {
            "username": str(user),  # Store as "Username#discriminator"
            "points": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "games_played": 0
        }

    player_data = scores_data[guild_id_str][user_id_str]
    player_data["username"] = str(user)  # Update username in case it changed
    player_data["points"] += points_change
    player_data["games_played"] += 1

    if outcome == "win":
        player_data["wins"] += 1
    elif outcome == "loss":
        player_data["losses"] += 1
    elif outcome == "tie":
        player_data["ties"] += 1

    save_scores()


# --- Duel State Management (_clear_duel_data_for_user, cancel_duel_and_cleanup - keep similar) ---
def _clear_duel_data_for_user(user_id):
    if user_id in active_duels:
        del active_duels[user_id]


async def cancel_duel_and_cleanup(p1_id, p2_id, channel_id_for_msg=None, reason_channel_msg=None, reason_dm_p1=None,
                                  reason_dm_p2=None):
    # ... (keep this function as it was, it's for duel cancellation, not stat updates)
    if channel_id_for_msg and reason_channel_msg:
        try:
            channel = bot.get_channel(channel_id_for_msg)
            if channel:
                await channel.send(reason_channel_msg)
        except discord.Forbidden:
            print(f"Error: Bot lacks permission to send cancellation message in channel {channel_id_for_msg}.")
        except discord.HTTPException as e:
            print(f"Error: HTTP error sending cancellation message to channel {channel_id_for_msg}: {e}")

    if p1_id and reason_dm_p1:
        try:
            user1 = await bot.fetch_user(p1_id)
            await user1.send(reason_dm_p1)
        except (discord.Forbidden, discord.HTTPException):
            pass

    if p2_id and reason_dm_p2:
        try:
            user2 = await bot.fetch_user(p2_id)
            await user2.send(reason_dm_p2)
        except (discord.Forbidden, discord.HTTPException):
            pass

    _clear_duel_data_for_user(p1_id)
    _clear_duel_data_for_user(p2_id)


# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})')
    load_scores()
    try:
        synced = await bot.tree.sync()  # Syncs all commands including /stats
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    # ... (rest of on_ready)
    print("\nConnected to Guilds:")
    if not bot.guilds: print("Not connected to any guilds.")
    for guild in bot.guilds: print(f"- {guild.name} (ID: {guild.id}), Members: {guild.member_count}")
    print("--- Bot is Ready ---")


@bot.event
async def on_message(message):
    if message.author.bot: return
    await bot.process_commands(message)


# --- Slash Commands ---
# /start, /duel, /accept, /decline, /drop - keep these largely the same,
# just ensure guild_id is available when calling update_player_stats

# ... (Keep /start, /duel, /accept, /decline, /drop as they were in the last working version)
# For brevity, I'll omit them here, but they should remain. The crucial part is the
# `run_game_flow` function changes.

# NEW /stats COMMAND
@bot.tree.command(name="stats", description="Display game statistics for a user or the server.")
@app_commands.describe(user="The user to get stats for (optional, defaults to yourself).")
async def stats_command(interaction: discord.Interaction, user: discord.Member = None):
    if not interaction.guild_id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    target_user = user if user else interaction.user

    stats = get_player_stats(interaction.guild_id, target_user.id)

    # Update username if it's the default or doesn't match current
    if stats["username"] == "Unknown User" or stats["username"] != str(target_user):
        stats["username"] = str(target_user)
        # If we want to save this potential username update, we'd need a small save mechanism here
        # For now, it's just for display in this command instance.
        # A more robust way is to ensure update_player_stats updates username on every game.

    embed = discord.Embed(
        title=f"📊 Stats for {stats['username']}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Points", value=str(stats['points']), inline=True)
    embed.add_field(name="Games Played", value=str(stats['games_played']), inline=True)
    embed.add_field(name="Wins", value=str(stats['wins']), inline=True)
    embed.add_field(name="Losses", value=str(stats['losses']), inline=True)
    embed.add_field(name="Ties", value=str(stats['ties']), inline=True)

    win_rate = 0
    if stats['games_played'] > 0 and (stats['wins'] + stats['losses'] > 0):  # Avoid division by zero if only ties
        win_rate = (stats['wins'] / (stats['wins'] + stats['losses'])) * 100 if (stats['wins'] + stats[
            'losses']) > 0 else 0
    embed.add_field(name="Win Rate (W/L)", value=f"{win_rate:.2f}%", inline=True)

    embed.set_footer(text=f"Stats from server: {interaction.guild.name}")

    try:
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to send embeds here.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"Error sending stats: {e}", ephemeral=True)


# --- Game Flow Logic (MODIFIED TO UPDATE NEW STATS) ---
async def run_game_flow(original_channel: discord.TextChannel, player1: discord.User, player2: discord.User):
    global GLOBAL_GAME_ROUND
    GLOBAL_GAME_ROUND += 1
    current_round_num = GLOBAL_GAME_ROUND
    guild_id = original_channel.guild.id  # Get guild_id for stats

    print(f"DEBUG run_game_flow: Entered for P1:{player1.id}, P2:{player2.id} in G:{guild_id}")
    # ... (initial state checks, role assignment - largely the same)
    p1_duel_data = active_duels.get(player1.id)
    p2_duel_data = active_duels.get(player2.id)

    if not (p1_duel_data and p2_duel_data and \
            p1_duel_data.get('opponent_id') == player2.id and \
            p2_duel_data.get('opponent_id') == player1.id and \
            p1_duel_data.get('game_state') == 'awaiting_roles' and \
            p2_duel_data.get('game_state') == 'awaiting_roles'):
        print(
            f"DEBUG run_game_flow: Initial state check FAILED. P1 State: {p1_duel_data.get('game_state') if p1_duel_data else 'No P1 Data'}. P2 State: {p2_duel_data.get('game_state') if p2_duel_data else 'No P2 Data'}")
        if original_channel:
            try:
                await original_channel.send(
                    "A critical error occurred with duel tracking (initial state). The game has been cancelled.")
            except (discord.Forbidden, discord.HTTPException):
                pass
        _clear_duel_data_for_user(player1.id)
        _clear_duel_data_for_user(player2.id)
        return

    roles = [player1, player2]
    random.shuffle(roles)
    dropper, checker = roles[0], roles[1]
    print(f"DEBUG run_game_flow: Roles assigned. Dropper: {dropper.id}, Checker: {checker.id}")

    active_duels[player1.id]['game_state'] = 'awaiting_numbers'
    active_duels[player2.id]['game_state'] = 'awaiting_numbers'
    # ... (set dropper_id, checker_id if needed)

    try:
        # ... (role announcement - keep as is)
        await original_channel.send(
            f"{dropper.mention} is the **Dropper**, and {checker.mention} is the **Checker**!\nThe Dropper is ready to drop the handkerchief!")
    except (discord.Forbidden, discord.HTTPException) as e:
        # ... (error handling for role announcement - keep as is)
        error_msg = "I don't have permission to announce roles in the channel." if isinstance(e,
                                                                                              discord.Forbidden) else f"Server error announcing roles: {e}."
        print(f"DEBUG run_game_flow: FAILED to send role announcement: {error_msg}")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      reason_channel_msg=f"{error_msg} Duel setup failed, game cancelled.",
                                      reason_dm_p1=f"{error_msg} Duel cancelled.",
                                      reason_dm_p2=f"{error_msg} Duel cancelled.")
        return

    # ... (get_player_number_via_dm helper function - keep as is, with its debug prints)
    async def get_player_number_via_dm(player: discord.User, role_name: str, opponent_name: str):
        # ... (implementation from previous working version)
        player_duel_data = active_duels.get(player.id)
        current_game_state = player_duel_data.get('game_state') if player_duel_data else 'No duel data for player'

        if not (player_duel_data and current_game_state == 'awaiting_numbers'):
            return None

        dm_text = f"🎉 You are the **{role_name}** ... You have {RESPONSE_TIMEOUT:.0f} seconds..."
        try:
            dm_channel = await player.create_dm()
            await dm_channel.send(dm_text)
        except discord.Forbidden:
            raise DMDisabledError(player)
        except discord.HTTPException as e:
            raise DMHttpError(player, e)

        def check(m: discord.Message):
            current_check_player_duel_data = active_duels.get(player.id)
            if not (current_check_player_duel_data and current_check_player_duel_data.get(
                    'game_state') == 'awaiting_numbers'):
                return False
            return m.author.id == player.id and m.channel.id == dm_channel.id and \
                m.content.isdigit() and 1 <= int(m.content) <= MAX_NUMBER

        try:
            response_msg = await bot.wait_for('message', check=check, timeout=RESPONSE_TIMEOUT)
            return int(response_msg.content)
        except asyncio.TimeoutError:
            current_timeout_player_duel_data = active_duels.get(player.id)
            if not (current_timeout_player_duel_data and current_timeout_player_duel_data.get(
                    'game_state') == 'awaiting_numbers'):
                return None
            try:
                await player.send("You took too long to respond! Duel cancelled.")
            except:
                pass
            raise PlayerTimedOutError(player)

    dropper_choice, checker_choice = None, None
    try:
        # ... (DM task creation and awaiting - keep as is, with its debug prints)
        dropper_task = asyncio.create_task(get_player_number_via_dm(dropper, "Dropper", checker.display_name))
        checker_task = asyncio.create_task(get_player_number_via_dm(checker, "Checker", dropper.display_name))

        done, pending = await asyncio.wait([dropper_task, checker_task], return_when=asyncio.FIRST_COMPLETED)
        exception_raised = None;
        results_map = {}
        for task in done:
            try:
                result = task.result()
                if task is dropper_task:
                    results_map['dropper'] = result
                elif task is checker_task:
                    results_map['checker'] = result
            except Exception as e:
                exception_raised = e; [p.cancel() for p in pending]; break
        if exception_raised: raise exception_raised
        if pending:
            try:
                remaining_task = list(pending)[0]
                if not remaining_task.cancelled():
                    result = await remaining_task
                    if remaining_task is dropper_task:
                        results_map['dropper'] = result
                    elif remaining_task is checker_task:
                        results_map['checker'] = result
            except Exception as e:
                raise e
        dropper_choice = results_map.get('dropper');
        checker_choice = results_map.get('checker')
        if dropper_choice is None and active_duels.get(dropper.id, {}).get('game_state') == 'awaiting_numbers':
            if not exception_raised: raise PlayerTimedOutError(dropper)
        if checker_choice is None and active_duels.get(checker.id, {}).get('game_state') == 'awaiting_numbers':
            if not exception_raised: raise PlayerTimedOutError(checker)

    except (DMDisabledError, DMHttpError, PlayerTimedOutError, asyncio.CancelledError, Exception) as e:
        # ... (error handling for DM process - keep as is, ensure cancel_duel_and_cleanup is called)
        # This part should remain the same as the last working version.
        # For brevity, I'm not repeating the detailed print statements here.
        # Just ensure it correctly calls cancel_duel_and_cleanup and returns.
        if isinstance(e, DMDisabledError):
            await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                          f"DM to {e.player.mention} failed (disabled). Duel cancelled.")
        elif isinstance(e, DMHttpError):
            await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                          f"DM to {e.player.mention} failed (HTTP error). Duel cancelled.")
        elif isinstance(e, PlayerTimedOutError):
            p_duel_data = active_duels.get(e.player.id)
            if p_duel_data and p_duel_data.get('game_state') == 'awaiting_numbers':
                await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                              f"{e.player.mention} timed out. Duel cancelled.")
        elif isinstance(e, asyncio.CancelledError):
            if active_duels.get(player1.id) or active_duels.get(player2.id):
                await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                              "Game cancelled due to responsiveness issue.")
        else:  # Generic Exception
            await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                          "Unexpected game error. Duel cancelled.")
        return

    if not (active_duels.get(player1.id) and active_duels.get(player2.id)):
        print("DEBUG run_game_flow: Duel was cancelled during number collection, not proceeding to result.")
        return
    if dropper_choice is None or checker_choice is None:
        print(f"DEBUG run_game_flow: ERROR - Numbers not collected. Cancelling.")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      "Internal error collecting numbers. Duel cancelled.")
        return

    # --- Result Determination and STATS UPDATE ---
    points_awarded_to_dropper = 0
    points_awarded_to_checker = 0
    dropper_outcome = "tie"
    checker_outcome = "tie"
    result_text = "It's a tie!"

    if dropper_choice > checker_choice:
        result_text = "The Dropper outsmarted the Checker!"
        points_awarded_to_dropper = POINTS_PER_DUEL_WIN
        dropper_outcome = "win"
        checker_outcome = "loss"
    elif checker_choice > dropper_choice:
        result_text = "Successful check!"
        points_awarded_to_checker = POINTS_PER_DUEL_WIN
        checker_outcome = "win"
        dropper_outcome = "loss"

    # Update stats for both players
    update_player_stats(guild_id, dropper, dropper_outcome, points_awarded_to_dropper)
    update_player_stats(guild_id, checker, checker_outcome, points_awarded_to_checker)

    # --- Result Announcement (using new get_player_stats for scores) ---
    dropper_current_stats = get_player_stats(guild_id, dropper.id)
    checker_current_stats = get_player_stats(guild_id, checker.id)

    result_message_lines = [
        "====𝐃𝐫𝐨𝐩 𝐓𝐡𝐞 𝐇𝐚𝐧𝐝𝐤𝐞𝐫𝐜𝐡𝐢𝐞𝐟====",
        f"Round {current_round_num}",
        " ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
        f"{dropper.mention} Dropped: {dropper_choice}",
        f"{checker.mention} Checked: {checker_choice}",
        " ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
        f"***RESULT: {result_text}***"
    ]
    if dropper_outcome == "win":
        result_message_lines.append(f"{dropper.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_awarded_to_dropper} points**")
    elif checker_outcome == "win":
        result_message_lines.append(f"{checker.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_awarded_to_checker} points**")

    result_message_lines.extend([
        " ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
        f"{dropper.mention} ({dropper_current_stats['points']}/{MAX_SCORE_DISPLAY})",  # Using new stats for display
        f"{checker.mention} ({checker_current_stats['points']}/{MAX_SCORE_DISPLAY})"
    ])

    try:
        await original_channel.send("\n".join(result_message_lines))
    except (discord.Forbidden, discord.HTTPException) as e:
        # ... (error handling for result announcement - keep as is)
        print(f"Error sending result message to channel: {e}")
        dm_fallback_p1 = f"Game ended, but I couldn't announce results in the server channel.\n" \
                         f"Result: {result_text}\nYour score: {dropper_current_stats['points']}/{MAX_SCORE_DISPLAY}\n" \
                         f"Opponent score: {checker_current_stats['points']}/{MAX_SCORE_DISPLAY}"
        dm_fallback_p2 = f"Game ended, but I couldn't announce results in the server channel.\n" \
                         f"Result: {result_text}\nYour score: {checker_current_stats['points']}/{MAX_SCORE_DISPLAY}\n" \
                         f"Opponent score: {dropper_current_stats['points']}/{MAX_SCORE_DISPLAY}"
        try:
            await (dropper if player1 == dropper else player2).send(
                dm_fallback_p1 if player1 == dropper else dm_fallback_p2)
        except:
            pass
        try:
            await (checker if player1 == checker else player2).send(
                dm_fallback_p2 if player1 == checker else dm_fallback_p1)
        except:
            pass

    # --- Cleanup ---
    _clear_duel_data_for_user(player1.id)
    _clear_duel_data_for_user(player2.id)
    print(f"DEBUG run_game_flow: Game finished and cleaned up for P1:{player1.id}, P2:{player2.id}")


if __name__ == "__main__":
    if not BOT_TOKEN: # Check if the token was loaded successfully
        print("Error: DISCORD_TOKEN not found in environment or .env file.")
        print("Please ensure 'secret.env' exists and contains DISCORD_TOKEN=YOUR_TOKEN")
    else:
        # Remove the hardcoded token warning as it's no longer applicable
        # print("###########################################################################")
        # print("!!! WARNING: YOU ARE USING A HARDCODED BOT TOKEN IN YOUR SCRIPT !!!")
        # ...
        # print("###########################################################################")
        print("\nAttempting to run the bot using token from environment...")
        try:
            bot.run(BOT_TOKEN)
        except discord.LoginFailure:
            print("!!! LOGIN FAILED: Invalid token loaded from environment.")
            print("!!! Please check your DISCORD_TOKEN in 'secret.env'.")
        except discord.PrivilegedIntentsRequired:
            print("!!! PRIVILEGED INTENTS REQUIRED: Enable Presence, Server Members, and Message Content Intents in the Discord Developer Portal.")
        except Exception as e:
            print(f"Unexpected error running bot: {e}")