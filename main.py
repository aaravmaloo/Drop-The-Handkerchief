import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
import os  # Import the os module
from dotenv import load_dotenv  # Import load_dotenv
import traceback  # For more detailed error logging in on_command_error

# --- Load Environment Variables ---
load_dotenv('auth.env')  # Load variables from auth.env

# --- Configuration ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

SCORE_FILE = "scores.json"
POINTS_PER_DUEL_WIN = 10
RESPONSE_TIMEOUT = 30.0
MAX_NUMBER = 60
MAX_SCORE_DISPLAY = 300

# --- Global State ---
scores_data = {}  # Will hold the nested structure: {guild_id: {user_id: {stats}}}
active_duels = {}
GLOBAL_GAME_ROUND = 0

# --- Intents Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)  # Prefix for potential text commands


# --- Helper Classes for Custom Errors ---
class DMInteractionError(Exception):
    def __init__(self, player, message="DM interaction failed."):
        self.player = player
        self.message = message
        super().__init__(self.message)


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
def load_scores_data():  # Renamed to avoid confusion with old 'scores'
    global scores_data
    try:
        with open(SCORE_FILE, 'r') as f:
            scores_data = json.load(f)
    except FileNotFoundError:
        scores_data = {}
        print(f"Info: {SCORE_FILE} not found. Starting with empty scores data.")
    except json.JSONDecodeError:
        print(f"Warning: {SCORE_FILE} is corrupted. Starting with empty scores data.")
        scores_data = {}


def save_scores_data():  # Renamed
    with open(SCORE_FILE, 'w') as f:
        json.dump(scores_data, f, indent=4)


def get_player_stats(guild_id: int, user_id: int):
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)
    if guild_id_str in scores_data and user_id_str in scores_data[guild_id_str]:
        return scores_data[guild_id_str][user_id_str].copy()  # Return a copy
    return {
        "username": "Unknown User",
        "points": 0, "wins": 0, "losses": 0, "ties": 0, "games_played": 0
    }


def update_player_stats(guild_id: int, user: discord.User, outcome: str, points_change: int):
    guild_id_str = str(guild_id)
    user_id_str = str(user.id)

    if guild_id_str not in scores_data:
        scores_data[guild_id_str] = {}
    if user_id_str not in scores_data[guild_id_str]:
        scores_data[guild_id_str][user_id_str] = {
            "username": str(user), "points": 0, "wins": 0,
            "losses": 0, "ties": 0, "games_played": 0
        }

    player_data = scores_data[guild_id_str][user_id_str]
    player_data["username"] = str(user)
    player_data["points"] += points_change
    player_data["games_played"] += 1
    if outcome == "win":
        player_data["wins"] += 1
    elif outcome == "loss":
        player_data["losses"] += 1
    elif outcome == "tie":
        player_data["ties"] += 1
    save_scores_data()


# --- Duel State Management ---
def _clear_duel_data_for_user(user_id):
    if user_id in active_duels: del active_duels[user_id]


async def cancel_duel_and_cleanup(p1_id, p2_id, channel_id_for_msg=None, reason_channel_msg=None, reason_dm_p1=None,
                                  reason_dm_p2=None):
    if channel_id_for_msg and reason_channel_msg:
        try:
            channel = bot.get_channel(channel_id_for_msg)
            if channel: await channel.send(reason_channel_msg)
        except discord.Forbidden:
            print(f"Error: Bot lacks permission for cancel msg in channel {channel_id_for_msg}.")
        except discord.HTTPException as e:
            print(f"Error: HTTP error for cancel msg in channel {channel_id_for_msg}: {e}")
    if p1_id and reason_dm_p1:
        try:
            await (await bot.fetch_user(p1_id)).send(reason_dm_p1)
        except:
            pass
    if p2_id and reason_dm_p2:
        try:
            await (await bot.fetch_user(p2_id)).send(reason_dm_p2)
        except:
            pass
    _clear_duel_data_for_user(p1_id)
    _clear_duel_data_for_user(p2_id)


# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id})')
    load_scores_data()
    try:
        # GUILD_ID_FOR_TESTING = discord.Object(id=YOUR_TEST_SERVER_ID) # For faster testing
        # bot.tree.copy_global_to(guild=GUILD_ID_FOR_TESTING)
        # synced = await bot.tree.sync(guild=GUILD_ID_FOR_TESTING)
        synced = await bot.tree.sync()  # Global sync
        print(f"Synced {len(synced)} command(s)")
        if synced:
            for cmd in synced: print(f"  - Synced: /{cmd.name} (ID: {cmd.id})")
        else:
            print("  - No commands were synced (already up-to-date or issue).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    print("\nConnected to Guilds:")
    if not bot.guilds: print("Not connected to any guilds.")
    for guild in bot.guilds: print(f"- {guild.name} (ID: {guild.id}), Members: {guild.member_count}")
    print("--- Bot is Ready ---")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    await bot.process_commands(message)  # Processes text-based commands if any were defined


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        # print(f"Debug: Text command not found: {ctx.invoked_with}") # Optional
        pass  # Silently ignore CommandNotFound for text commands
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"Missing argument(s) for `{ctx.command.name}`. Usage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            ephemeral=True)
    elif isinstance(error, commands.CommandInvokeError):
        print(f"Error in command {ctx.command.qualified_name}: {error.original}")
        traceback.print_exception(type(error.original), error.original, error.original.__traceback__)
        await ctx.send(f"An error occurred while running the command: {error.original}", ephemeral=True)
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.", ephemeral=True)
    else:
        print(f'Unhandled command error: {error}')
        traceback.print_exception(type(error), error, error.__traceback__)


# --- Slash Commands ---
@bot.tree.command(name="start", description="Start a simple random role assignment (test command).")
async def start_command(interaction: discord.Interaction):
    try:
        role = random.choice(["Dropper", "Checker"])
        await interaction.response.send_message(f"Random role result: **{role}**")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="duel", description="Challenge another user to a Drop the Handkerchief duel.")
@app_commands.describe(opponent="The user you want to duel.")
async def duel_command(interaction: discord.Interaction, opponent: discord.Member):
    challenger = interaction.user
    if opponent.id == challenger.id:
        await interaction.response.send_message("You can't duel yourself!", ephemeral=True);
        return
    if opponent.bot:
        await interaction.response.send_message("You can't duel a bot!", ephemeral=True);
        return
    if challenger.id in active_duels or opponent.id in active_duels:
        msg = "One of you is already in a duel or has a pending challenge! Please wait."
        # ... (more specific messages as before)
        await interaction.response.send_message(msg, ephemeral=True);
        return

    active_duels[challenger.id] = {'opponent_id': opponent.id, 'channel_id': interaction.channel_id,
                                   'guild_id': interaction.guild_id, 'is_challenger': True,
                                   'game_state': 'pending_acceptance'}
    active_duels[opponent.id] = {'opponent_id': challenger.id, 'channel_id': interaction.channel_id,
                                 'guild_id': interaction.guild_id, 'is_challenger': False,
                                 'game_state': 'pending_acceptance'}
    try:
        await interaction.response.send_message(
            f"{challenger.mention} has challenged {opponent.mention}!\n"
            f"{opponent.mention}, use `/accept` or `/decline`.\n"
            f"{challenger.mention}, use `/drop` to cancel."
        )
    except Exception as e:
        await interaction.followup.send(f"Error sending duel challenge: {e}", ephemeral=True)
        await cancel_duel_and_cleanup(challenger.id, opponent.id, interaction.channel_id)


@bot.tree.command(name="accept", description="Accept a Drop the Handkerchief duel challenge.")
async def accept_command(interaction: discord.Interaction):
    acceptor = interaction.user
    acceptor_duel_info = active_duels.get(acceptor.id)
    if not acceptor_duel_info or acceptor_duel_info.get('is_challenger') or acceptor_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid pending challenge to accept, or you initiated it.",
                                                ephemeral=True);
        return

    challenger_id = acceptor_duel_info['opponent_id']
    challenger_duel_info = active_duels.get(challenger_id)
    if not challenger_duel_info or challenger_duel_info.get(
            'game_state') != 'pending_acceptance' or challenger_duel_info.get('opponent_id') != acceptor.id:
        await interaction.response.send_message("Challenge no longer valid.", ephemeral=True)
        _clear_duel_data_for_user(acceptor.id);
        _clear_duel_data_for_user(challenger_id)
        return

    acceptor_duel_info['game_state'] = 'awaiting_roles';
    challenger_duel_info['game_state'] = 'awaiting_roles'
    try:
        challenger_user = await bot.fetch_user(challenger_id)
    except discord.NotFound:
        await interaction.response.send_message("Challenger not found. Duel cancelled.", ephemeral=True)
        await cancel_duel_and_cleanup(acceptor.id, challenger_id, acceptor_duel_info.get('channel_id'));
        return
    try:
        await interaction.response.send_message(
            f"{acceptor.mention} accepted duel against {challenger_user.mention}! Game on!")
    except Exception as e:
        await interaction.followup.send(f"Error sending acceptance: {e}", ephemeral=True)
        await cancel_duel_and_cleanup(acceptor.id, challenger_id, acceptor_duel_info.get('channel_id'),
                                      reason_dm_p1="Failed to announce acceptance.",
                                      reason_dm_p2="Acceptance failed to announce.");
        return
    await run_game_flow(interaction.channel, acceptor, challenger_user)


@bot.tree.command(name="decline", description="Decline a pending duel challenge made against you.")
async def decline_command(interaction: discord.Interaction):
    decliner = interaction.user;
    decliner_duel_info = active_duels.get(decliner.id)
    if not decliner_duel_info or decliner_duel_info.get('is_challenger') or decliner_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid challenge to decline, or you initiated it.", ephemeral=True);
        return

    challenger_id = decliner_duel_info['opponent_id']
    challenger_user = await bot.fetch_user(challenger_id) if challenger_id else None
    msg = f"You declined the challenge from {challenger_user.mention if challenger_user else 'challenger'}."
    await interaction.response.send_message(msg)
    reason_ch = f"{decliner.mention} declined duel from {challenger_user.mention if challenger_user else 'User'}"
    reason_dm_challenger = f"{decliner.mention} declined your challenge."
    await cancel_duel_and_cleanup(decliner.id, challenger_id, decliner_duel_info.get('channel_id'), reason_ch,
                                  reason_dm_p2=reason_dm_challenger if challenger_user else None)


@bot.tree.command(name="drop", description="Cancel a duel challenge you initiated before it's accepted.")
async def drop_command(interaction: discord.Interaction):
    challenger = interaction.user;
    challenger_duel_info = active_duels.get(challenger.id)
    if not challenger_duel_info or not challenger_duel_info.get('is_challenger') or challenger_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid challenge initiated by you to drop.", ephemeral=True);
        return

    opponent_id = challenger_duel_info['opponent_id']
    opponent_user = await bot.fetch_user(opponent_id) if opponent_id else None
    msg = f"You cancelled your challenge to {opponent_user.mention if opponent_user else 'opponent'}."
    await interaction.response.send_message(msg)
    reason_ch = f"{challenger.mention} dropped challenge to {opponent_user.mention if opponent_user else 'User'}"
    reason_dm_opponent = f"{challenger.mention} dropped their challenge to you."
    await cancel_duel_and_cleanup(challenger.id, opponent_id, challenger_duel_info.get('channel_id'), reason_ch,
                                  reason_dm_p2=reason_dm_opponent if opponent_user else None)


@bot.tree.command(name="stats", description="Display game statistics for a user or the server.")
@app_commands.describe(user="The user to get stats for (optional, defaults to yourself).")
async def stats_command(interaction: discord.Interaction, user: discord.Member = None):
    if not interaction.guild_id:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True);
        return
    target_user = user if user else interaction.user
    stats = get_player_stats(interaction.guild_id, target_user.id)
    if stats["username"] == "Unknown User" or stats["username"] != str(target_user): stats["username"] = str(
        target_user)
    embed = discord.Embed(title=f"📊 Stats for {stats['username']}", color=discord.Color.blue())
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Points", value=str(stats['points']), inline=True)
    embed.add_field(name="Games Played", value=str(stats['games_played']), inline=True)
    embed.add_field(name="Wins", value=str(stats['wins']), inline=True)
    embed.add_field(name="Losses", value=str(stats['losses']), inline=True)
    embed.add_field(name="Ties", value=str(stats['ties']), inline=True)
    win_rate = (stats['wins'] / (stats['wins'] + stats['losses'])) * 100 if (stats['wins'] + stats['losses']) > 0 else 0
    embed.add_field(name="Win Rate (W/L)", value=f"{win_rate:.2f}%", inline=True)
    embed.set_footer(text=f"Stats from server: {interaction.guild.name}")
    try:
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"Error sending stats: {e}", ephemeral=True)


# --- Game Flow Logic ---
async def run_game_flow(original_channel: discord.TextChannel, player1: discord.User, player2: discord.User):
    global GLOBAL_GAME_ROUND
    GLOBAL_GAME_ROUND += 1
    current_round_num = GLOBAL_GAME_ROUND
    guild_id = original_channel.guild.id

    print(f"DEBUG run_game_flow: Entered P1:{player1.id}, P2:{player2.id} in G:{guild_id}")
    p1_data = active_duels.get(player1.id);
    p2_data = active_duels.get(player2.id)
    if not (p1_data and p2_data and p1_data.get('opponent_id') == player2.id and p2_data.get(
            'opponent_id') == player1.id and p1_data.get('game_state') == 'awaiting_roles' and p2_data.get(
            'game_state') == 'awaiting_roles'):
        print(
            f"DEBUG run_game_flow: Initial state FAILED. P1: {p1_data.get('game_state') if p1_data else 'N/A'}, P2: {p2_data.get('game_state') if p2_data else 'N/A'}")
        if original_channel:
            try:
                await original_channel.send("Critical duel tracking error. Game cancelled.")
            except Exception as e: # Good practice to catch specific exceptions or at least log it
                print(f"Error sending critical error message to channel: {e}")
                pass # Continue to cleanup even if sending the message fails

        # These lines should be at the same indentation level as the 'if original_channel:'
        # if they are meant to run regardless of whether the message was sent,
        # or inside the 'if not (p1_data...)' block's main scope.
        _clear_duel_data_for_user(player1.id)
        _clear_duel_data_for_user(player2.id)
        return

    roles = [player1, player2];
    random.shuffle(roles)
    dropper, checker = roles[0], roles[1]
    print(f"DEBUG run_game_flow: Roles: Dropper={dropper.id}, Checker={checker.id}")
    active_duels[player1.id]['game_state'] = 'awaiting_numbers';
    active_duels[player2.id]['game_state'] = 'awaiting_numbers'

    try:
        await original_channel.send(
            f"{dropper.mention} is Dropper, {checker.mention} is Checker! Dropper, drop the handkerchief!")
    except Exception as e:
        err_msg = "Perm error announcing roles." if isinstance(e, discord.Forbidden) else f"Server error: {e}"
        print(f"DEBUG run_game_flow: FAILED role announcement: {err_msg}")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id, f"{err_msg} Game cancelled.",
                                      f"{err_msg} Duel cancelled.", f"{err_msg} Duel cancelled.");
        return

    async def get_player_number_via_dm(player: discord.User, role_name: str, opponent_name: str):
        p_data = active_duels.get(player.id)
        if not (p_data and p_data.get('game_state') == 'awaiting_numbers'):
            print(
                f"DEBUG get_player_number_via_dm: State FAILED for {player.name}. State: {p_data.get('game_state') if p_data else 'N/A'}")
            return None
        dm_text = f"🎉 You are **{role_name}**! Pick number (1-{MAX_NUMBER}) vs {opponent_name}. {RESPONSE_TIMEOUT:.0f}s."
        try:
            dm_ch = await player.create_dm();
            await dm_ch.send(dm_text)
        except discord.Forbidden:
            print(f"DEBUG DM FORBIDDEN: {player.name}"); raise DMDisabledError(player)
        except discord.HTTPException as e:
            print(f"DEBUG DM HTTP ERR: {player.name} {e}"); raise DMHttpError(player, e)

        def check_msg(m):
            cp_data = active_duels.get(player.id)
            return cp_data and cp_data.get('game_state') == 'awaiting_numbers' and \
                m.author.id == player.id and m.channel.id == dm_ch.id and \
                m.content.isdigit() and 1 <= int(m.content) <= MAX_NUMBER

        try:
            resp_msg = await bot.wait_for('message', check=check_msg, timeout=RESPONSE_TIMEOUT)
            return int(resp_msg.content)
        except asyncio.TimeoutError:
            ct_data = active_duels.get(player.id)
            if not (ct_data and ct_data.get('game_state') == 'awaiting_numbers'): return None
            try:
                await player.send("Too slow! Duel cancelled.")
            except:
                pass
            raise PlayerTimedOutError(player)

    dropper_choice, checker_choice = None, None
    try:
        print(f"DEBUG run_game_flow: Creating DM tasks. D_ID:{dropper.id}, C_ID:{checker.id}")
        dropper_task = asyncio.create_task(get_player_number_via_dm(dropper, "Dropper", checker.display_name))
        checker_task = asyncio.create_task(get_player_number_via_dm(checker, "Checker", dropper.display_name))
        done, pending = await asyncio.wait([dropper_task, checker_task], return_when=asyncio.FIRST_COMPLETED)
        exc_raised = None;
        res_map = {}
        for task in done:
            try:
                res = task.result()
                if task is dropper_task:
                    res_map['dropper'] = res
                elif task is checker_task:
                    res_map['checker'] = res
            except Exception as e:
                exc_raised = e; [p.cancel() for p in pending]; break
        if exc_raised: raise exc_raised
        if pending:
            try:
                rem_task = list(pending)[0]
                if not rem_task.cancelled():
                    res = await rem_task
                    if rem_task is dropper_task:
                        res_map['dropper'] = res
                    elif rem_task is checker_task:
                        res_map['checker'] = res
            except Exception as e:
                raise e
        dropper_choice = res_map.get('dropper');
        checker_choice = res_map.get('checker')
        print(f"DEBUG run_game_flow: Results: D_Choice={dropper_choice}, C_Choice={checker_choice}")
        if dropper_choice is None and active_duels.get(dropper.id, {}).get('game_state') == 'awaiting_numbers':
            if not exc_raised: raise PlayerTimedOutError(dropper)
        if checker_choice is None and active_duels.get(checker.id, {}).get('game_state') == 'awaiting_numbers':
            if not exc_raised: raise PlayerTimedOutError(checker)
    except (DMDisabledError, DMHttpError, PlayerTimedOutError, asyncio.CancelledError) as e_detail:
        reason = "DM/Timeout issue"
        if isinstance(e_detail, DMDisabledError):
            reason = f"DM to {e_detail.player.mention} failed (disabled)."
        elif isinstance(e_detail, DMHttpError):
            reason = f"DM to {e_detail.player.mention} failed (HTTP error)."
        elif isinstance(e_detail, PlayerTimedOutError):
            p_data_timeout = active_duels.get(e_detail.player.id)
            if p_data_timeout and p_data_timeout.get('game_state') == 'awaiting_numbers':
                reason = f"{e_detail.player.mention} timed out."
            else:
                return  # Already handled
        elif isinstance(e_detail, asyncio.CancelledError):
            reason = "Responsiveness issue."
        print(f"DEBUG run_game_flow: Caught in DM block: {reason}")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id, f"{reason} Duel cancelled.");
        return
    except Exception as e_unexpected:
        print(f"DEBUG run_game_flow: UNEXPECTED error in DM block: {e_unexpected}")
        traceback.print_exc()
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      "Unexpected game error. Duel cancelled.");
        return

    if not (active_duels.get(player1.id) and active_duels.get(player2.id)):
        print("DEBUG run_game_flow: Duel cancelled during DMs, not proceeding.");
        return
    if dropper_choice is None or checker_choice is None:
        print(f"DEBUG run_game_flow: ERROR - Numbers not collected. D:{dropper_choice} C:{checker_choice}. Cancelling.")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      "Internal error collecting numbers. Duel cancelled.");
        return

    points_drop = 0;
    points_check = 0;
    drop_outcome = "tie";
    check_outcome = "tie";
    res_text = "It's a tie!"
    if dropper_choice > checker_choice:
        res_text = "Dropper outsmarted Checker!";
        points_drop = POINTS_PER_DUEL_WIN;
        drop_outcome = "win";
        check_outcome = "loss"
    elif checker_choice > dropper_choice:
        res_text = "Successful check!";
        points_check = POINTS_PER_DUEL_WIN;
        check_outcome = "win";
        drop_outcome = "loss"
    update_player_stats(guild_id, dropper, drop_outcome, points_drop)
    update_player_stats(guild_id, checker, check_outcome, points_check)

    drop_stats = get_player_stats(guild_id, dropper.id);
    check_stats = get_player_stats(guild_id, checker.id)
    res_lines = [
        "====𝐃𝐫𝐨𝐩 𝐓𝐡𝐞 𝐇𝐚𝐧𝐝𝐤𝐞𝐫𝐜𝐡𝐢𝐞𝐟====", f"Round {current_round_num}", " ~" * 15,
        f"{dropper.mention} Dropped: {dropper_choice}", f"{checker.mention} Checked: {checker_choice}", " ~" * 15,
        f"***RESULT: {res_text}***"
    ]
    if drop_outcome == "win":
        res_lines.append(f"{dropper.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_drop} points**")
    elif check_outcome == "win":
        res_lines.append(f"{checker.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_check} points**")
    res_lines.extend([" ~" * 15, f"{dropper.mention} ({drop_stats['points']}/{MAX_SCORE_DISPLAY})",
                      f"{checker.mention} ({check_stats['points']}/{MAX_SCORE_DISPLAY})"])
    try:
        await original_channel.send("\n".join(res_lines))
    except Exception as e_send_res:
        print(f"Error sending result msg: {e_send_res}")
        # Fallback DMs if channel send fails (simplified)
        try:
            await dropper.send(f"Game result: {res_text}. Your points: {drop_stats['points']}")
        except:
            pass
        try:
            await checker.send(f"Game result: {res_text}. Your points: {check_stats['points']}")
        except:
            pass
    _clear_duel_data_for_user(player1.id);
    _clear_duel_data_for_user(player2.id)
    print(f"DEBUG run_game_flow: Game finished for P1:{player1.id}, P2:{player2.id}")


# --- Run Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Error: DISCORD_TOKEN not found in auth.env.")
        print("Please ensure 'auth.env' exists with DISCORD_TOKEN=YOUR_TOKEN")
    else:
        print("\nAttempting to run bot using token from auth.env...")
        try:
            bot.run(BOT_TOKEN)
        except discord.LoginFailure:
            print("!!! LOGIN FAILED: Invalid token from auth.env.")
        except discord.PrivilegedIntentsRequired:
            print("!!! PRIVILEGED INTENTS REQUIRED: Enable Presence, Server Members, Message Content.")
        except Exception as e:
            print(f"Unexpected error running bot: {e}")