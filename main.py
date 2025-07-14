import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
import os
from dotenv import load_dotenv
import traceback

# --- Load Environment Variables ---
load_dotenv('auth.env')

# --- Configuration ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
SCORE_FILE = "scores.json"
POINTS_PER_DUEL_WIN = 10
RESPONSE_TIMEOUT = 30.0
MAX_NUMBER = 60
MAX_SCORE_DISPLAY = 300

# --- Global State ---
scores_data = {}
active_duels = {}
GLOBAL_GAME_ROUND = 0

# --- Intents Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)


# --- Helper Classes ---
class DMInteractionError(Exception):
    def __init__(self, player, message="DM interaction failed."):
        self.player = player;
        self.message = message;
        super().__init__(self.message)


class DMDisabledError(DMInteractionError):
    def __init__(self, player): super().__init__(player, f"DM disabled for {player.mention}.")


class DMHttpError(DMInteractionError):
    def __init__(self, player, original_exception): super().__init__(player,
                                                                     f"HTTP error sending DM to {player.mention}: {original_exception}"); self.original_exception = original_exception


class PlayerTimedOutError(DMInteractionError):
    def __init__(self, player): super().__init__(player, f"Player {player.mention} timed out.")


# --- Score Management ---
def load_scores_data():
    global scores_data
    try:
        with open(SCORE_FILE, 'r') as f:
            scores_data = json.load(f)
    except FileNotFoundError:
        scores_data = {}; print(f"Info: {SCORE_FILE} not found.")
    except json.JSONDecodeError:
        scores_data = {}; print(f"Warning: {SCORE_FILE} corrupted.")


def save_scores_data():
    with open(SCORE_FILE, 'w') as f: json.dump(scores_data, f, indent=4)


def get_player_stats(guild_id: int, user_id: int):
    gid_str, uid_str = str(guild_id), str(user_id)
    if gid_str in scores_data and uid_str in scores_data[gid_str]:
        return scores_data[gid_str][uid_str].copy()
    return {"username": "Unknown", "points": 0, "wins": 0, "losses": 0, "ties": 0, "games_played": 0}


def update_player_stats(guild_id: int, user: discord.User, outcome: str, points_change: int):
    gid_str, uid_str = str(guild_id), str(user.id)
    if gid_str not in scores_data: scores_data[gid_str] = {}
    if uid_str not in scores_data[gid_str]:
        scores_data[gid_str][uid_str] = {"username": str(user), "points": 0, "wins": 0, "losses": 0, "ties": 0,
                                         "games_played": 0}

    pd = scores_data[gid_str][uid_str]
    pd["username"] = str(user)
    pd["points"] += points_change
    pd["games_played"] += 1
    if outcome == "win":
        pd["wins"] += 1
    elif outcome == "loss":
        pd["losses"] += 1
    elif outcome == "tie":
        pd["ties"] += 1
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
        except Exception as e:
            print(f"Error sending cancel msg to ch {channel_id_for_msg}: {e}")
    if p1_id and reason_dm_p1:
        try:
            user1 = await bot.fetch_user(p1_id)
            await user1.send(reason_dm_p1)
        except Exception as e:  # print(f"Debug: Could not send DM to user {p1_id}: {e}")
            pass
    if p2_id and reason_dm_p2:
        try:
            user2 = await bot.fetch_user(p2_id)
            await user2.send(reason_dm_p2)
        except Exception as e:  # print(f"Debug: Could not send DM to user {p2_id}: {e}")
            pass
    _clear_duel_data_for_user(p1_id);
    _clear_duel_data_for_user(p2_id)


# --- Bot Events ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    load_scores_data()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        if synced:
            [print(f"  - Synced: /{cmd.name}") for cmd in synced]
        else:
            print("  - No new/changed commands to sync (already up-to-date or issue).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    print("\nConnected to Guilds:")
    if not bot.guilds:
        print("Not in any guilds.")
    else:
        [print(f"- {g.name} (ID: {g.id}), Members: {g.member_count}") for g in bot.guilds]
    print("--- Bot is Ready ---")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"Missing arg(s) for `{ctx.command.name}`. Usage: `{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            ephemeral=True)
    elif isinstance(error, commands.CommandInvokeError):
        print(f"Error in text command {ctx.command.qualified_name if ctx.command else 'UnknownCmd'}: {error.original}");
        traceback.print_exception(type(error.original), error.original, error.original.__traceback__)
        await ctx.send(f"Error running command: {error.original}", ephemeral=True)
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("No permission for this command.", ephemeral=True)
    else:
        print(f'Unhandled text command error: {error}'); traceback.print_exception(type(error), error,
                                                                                   error.__traceback__)


# --- Slash Commands ---
@bot.tree.command(name="start", description="Test random role assignment.")
async def start_command(interaction: discord.Interaction):
    try:
        await interaction.response.send_message(f"Random role: **{random.choice(['Dropper', 'Checker'])}**")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="duel", description="Challenge a user to Drop the Handkerchief.")
@app_commands.describe(opponent="The user to duel.")
async def duel_command(interaction: discord.Interaction, opponent: discord.Member):
    challenger = interaction.user

    # Quick validation checks before deferring
    if opponent.id == challenger.id:
        await interaction.response.send_message("Can't duel yourself!", ephemeral=True);
        return
    if opponent.bot:
        await interaction.response.send_message("Can't duel a bot!", ephemeral=True);
        return

    # Defer before potentially longer checks or main public response
    # The main successful outcome of /duel is a public message, so defer publicly.
    try:
        await interaction.response.defer(ephemeral=False, thinking=True)  # thinking=True shows "Bot is thinking..."
    except discord.errors.InteractionResponded:  # Already responded (e.g. if previous checks were too fast)
        pass  # We'll use followup then

    # Checks after deferral
    if challenger.id in active_duels or opponent.id in active_duels:
        await interaction.followup.send("One of you is already in a duel/pending challenge.", ephemeral=True);
        return

    active_duels[challenger.id] = {'opponent_id': opponent.id, 'channel_id': interaction.channel_id,
                                   'guild_id': interaction.guild_id, 'is_challenger': True,
                                   'game_state': 'pending_acceptance'}
    active_duels[opponent.id] = {'opponent_id': challenger.id, 'channel_id': interaction.channel_id,
                                 'guild_id': interaction.guild_id, 'is_challenger': False,
                                 'game_state': 'pending_acceptance'}

    try:
        await interaction.followup.send(  # Use followup after deferring
            f"{challenger.mention} challenged {opponent.mention}!\n"
            f"{opponent.mention}: `/accept` or `/decline`.\n"
            f"{challenger.mention}: `/drop` to cancel."
        )
    except Exception as e:
        try:
            await interaction.followup.send(f"Error sending duel challenge: {e}", ephemeral=True)
        except discord.errors.NotFound:  # Interaction might have fully expired
            if interaction.channel: await interaction.channel.send(
                f"Error setting up duel for {challenger.mention}: {e}", delete_after=15)
        await cancel_duel_and_cleanup(challenger.id, opponent.id, interaction.channel_id)


@bot.tree.command(name="accept", description="Accept a duel challenge.")
async def accept_command(interaction: discord.Interaction):
    # This command leads to a public message, so defer if checks are done first
    # However, validation is usually quick. Direct response for errors, then public for success.
    acceptor = interaction.user;
    acc_duel_info = active_duels.get(acceptor.id)
    if not acc_duel_info or acc_duel_info.get('is_challenger') or acc_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid pending challenge to accept, or you initiated it.",
                                                ephemeral=True);
        return

    chal_id = acc_duel_info['opponent_id'];
    chal_duel_info = active_duels.get(chal_id)
    if not chal_duel_info or chal_duel_info.get('game_state') != 'pending_acceptance' or chal_duel_info.get(
            'opponent_id') != acceptor.id:
        await interaction.response.send_message("Challenge no longer valid (dropped or error).", ephemeral=True)
        _clear_duel_data_for_user(acceptor.id);
        _clear_duel_data_for_user(chal_id);
        return

    # If we got here, we will send a public response.
    # Consider deferring if fetch_user could be slow, though it's usually fast.
    # For now, direct response path.
    acc_duel_info['game_state'] = 'awaiting_roles';
    chal_duel_info['game_state'] = 'awaiting_roles'
    try:
        chal_user = await bot.fetch_user(chal_id)
    except discord.NotFound:
        await interaction.response.send_message("Challenger not found. Duel cancelled.", ephemeral=True)
        await cancel_duel_and_cleanup(acceptor.id, chal_id, acc_duel_info.get('channel_id'));
        return
    try:
        await interaction.response.send_message(f"{acceptor.mention} accepted duel vs {chal_user.mention}! Game on!")
    except Exception as e:  # Could be InteractionResponded if defer was missed and logic took too long
        try:
            await interaction.followup.send(f"Error sending acceptance: {e}", ephemeral=True)
        except discord.errors.NotFound:
            if interaction.channel: await interaction.channel.send(f"Error accepting duel for {acceptor.mention}: {e}",
                                                                   delete_after=15)
        await cancel_duel_and_cleanup(acceptor.id, chal_id, acc_duel_info.get('channel_id'),
                                      reason_dm_p1="Failed acceptance announce.",
                                      reason_dm_p2="Acceptance announce failed.");
        return
    await run_game_flow(interaction.channel, acceptor, chal_user)


@bot.tree.command(name="decline", description="Decline a pending duel challenge.")
async def decline_command(interaction: discord.Interaction):
    decliner = interaction.user;
    dec_duel_info = active_duels.get(decliner.id)
    if not dec_duel_info or dec_duel_info.get('is_challenger') or dec_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid challenge to decline / you initiated it.", ephemeral=True);
        return

    chal_id = dec_duel_info['opponent_id']
    chal_user = None
    if chal_id:
        try:
            chal_user = await bot.fetch_user(chal_id)
        except:
            pass  # User might not be fetchable, still proceed

    # This is an initial response
    await interaction.response.send_message(
        f"You declined the challenge from {chal_user.mention if chal_user else 'the challenger'}.")

    # Followup actions (cleanup and potential channel message)
    reason_ch = f"{decliner.mention} declined duel from {chal_user.mention if chal_user else 'User ID ' + str(chal_id if chal_id else 'Unknown')}"
    reason_dm_challenger = f"{decliner.mention} declined your challenge."
    await cancel_duel_and_cleanup(decliner.id, chal_id, dec_duel_info.get('channel_id'),
                                  reason_channel_msg=reason_ch,  # Corrected keyword
                                  reason_dm_p2=reason_dm_challenger if chal_user else None)


@bot.tree.command(name="drop", description="Cancel your pending duel challenge.")
async def drop_command(interaction: discord.Interaction):
    challenger = interaction.user;
    chal_duel_info = active_duels.get(challenger.id)
    if not chal_duel_info or not chal_duel_info.get('is_challenger') or chal_duel_info.get(
            'game_state') != 'pending_acceptance':
        await interaction.response.send_message("No valid challenge by you to drop.", ephemeral=True);
        return

    opp_id = chal_duel_info['opponent_id']
    opp_user = None
    if opp_id:
        try:
            opp_user = await bot.fetch_user(opp_id)
        except:
            pass

    await interaction.response.send_message(
        f"You cancelled your challenge to {opp_user.mention if opp_user else 'your opponent'}.")

    reason_ch = f"{challenger.mention} dropped challenge to {opp_user.mention if opp_user else 'User ID ' + str(opp_id if opp_id else 'Unknown')}"
    reason_dm_opponent = f"{challenger.mention} dropped their challenge to you."
    await cancel_duel_and_cleanup(challenger.id, opp_id, chal_duel_info.get('channel_id'),
                                  reason_channel_msg=reason_ch,  # Corrected keyword
                                  reason_dm_p2=reason_dm_opponent if opp_user else None)


@bot.tree.command(name="stats", description="Display game statistics.")
@app_commands.describe(user="User to get stats for (optional, defaults to yourself).")
async def stats_command(interaction: discord.Interaction, user: discord.Member = None):
    if not interaction.guild_id: await interaction.response.send_message("Command for servers only.",
                                                                         ephemeral=True); return
    target_user = user if user else interaction.user
    stats = get_player_stats(interaction.guild_id, target_user.id)
    if stats["username"] == "Unknown" or stats["username"] != str(target_user): stats["username"] = str(target_user)

    embed = discord.Embed(title=f"📊 Stats for {stats['username']}", color=discord.Color.blue())
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="Points", value=str(stats['points']), inline=True);
    embed.add_field(name="Games", value=str(stats['games_played']), inline=True)
    embed.add_field(name="Wins", value=str(stats['wins']), inline=True);
    embed.add_field(name="Losses", value=str(stats['losses']), inline=True)
    embed.add_field(name="Ties", value=str(stats['ties']), inline=True)
    win_loss_games = stats['wins'] + stats['losses']
    win_rate = (stats['wins'] / win_loss_games) * 100 if win_loss_games > 0 else 0
    embed.add_field(name="Win Rate (W/L)", value=f"{win_rate:.2f}%", inline=True)
    embed.set_footer(text=f"Stats from server: {interaction.guild.name}")
    try:
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"Error sending stats: {e}", ephemeral=True)


# --- Game Flow Logic (with NEW RULES Interpretation A) ---
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
            f"DEBUG run_game_flow: Initial state FAILED. P1_state: {p1_data.get('game_state') if p1_data else 'N/A'}, P2_state: {p2_data.get('game_state') if p2_data else 'N/A'}")
        if original_channel:
            try:
                await original_channel.send("Critical duel tracking error. Game cancelled.")
            except Exception as e_ch_send:
                print(f"Debug: Failed to send critical error to ch: {e_ch_send}")
        _clear_duel_data_for_user(player1.id);
        _clear_duel_data_for_user(player2.id);
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
        err_msg = "Permission error announcing roles." if isinstance(e,
                                                                     discord.Forbidden) else f"Server error announcing roles: {e}"
        print(f"DEBUG run_game_flow: FAILED role announcement: {err_msg}")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      reason_channel_msg=f"{err_msg} Game cancelled.",  # Corrected keyword
                                      reason_dm_p1=f"{err_msg} Duel cancelled.",
                                      reason_dm_p2=f"{err_msg} Duel cancelled.");
        return

    async def get_player_number_via_dm(player: discord.User, role_name: str, opponent_name: str):
        p_data = active_duels.get(player.id)
        if not (p_data and p_data.get('game_state') == 'awaiting_numbers'):
            print(
                f"DEBUG get_player_number_via_dm: State FAILED for {player.name}. State: {p_data.get('game_state') if p_data else 'N/A'}")
            return None
        dm_text = f"🎉 You are **{role_name}**! Pick number (1-{MAX_NUMBER}) vs {opponent_name}. You have {RESPONSE_TIMEOUT:.0f}s."
        dm_ch = None  # Define dm_ch here for broader scope in check_msg
        try:
            dm_ch = await player.create_dm();
            await dm_ch.send(dm_text)
        except discord.Forbidden:
            print(f"DEBUG DM FORBIDDEN: {player.name}"); raise DMDisabledError(player)
        except discord.HTTPException as e_http:
            print(f"DEBUG DM HTTP ERR: {player.name} {e_http}"); raise DMHttpError(player, e_http)

        def check_msg(m: discord.Message):
            cp_data = active_duels.get(player.id)
            return cp_data and cp_data.get('game_state') == 'awaiting_numbers' and \
                m.author.id == player.id and dm_ch and m.channel.id == dm_ch.id and \
                m.content.isdigit() and 1 <= int(m.content) <= MAX_NUMBER

        try:
            resp_msg = await bot.wait_for('message', check=check_msg, timeout=RESPONSE_TIMEOUT)
            return int(resp_msg.content)
        except asyncio.TimeoutError:
            ct_data = active_duels.get(player.id)
            if not (ct_data and ct_data.get('game_state') == 'awaiting_numbers'): return None
            try:
                await player.send("You took too long to respond! Duel cancelled.")
            except:
                pass
            raise PlayerTimedOutError(player)

    dropper_choice, checker_choice = None, None
    try:
        print(f"DEBUG run_game_flow: Creating DM tasks. Dropper_ID:{dropper.id}, Checker_ID:{checker.id}")
        dropper_task = asyncio.create_task(get_player_number_via_dm(dropper, "Dropper", checker.display_name))
        checker_task = asyncio.create_task(get_player_number_via_dm(checker, "Checker", dropper.display_name))
        done, pending = await asyncio.wait([dropper_task, checker_task], return_when=asyncio.FIRST_COMPLETED)

        exc_raised = None;
        res_map = {}
        for task in done:
            try:
                res = task.result()
            except Exception as e_task_done:
                exc_raised = e_task_done; [p.cancel() for p in pending]; break
            if task is dropper_task:
                res_map['dropper'] = res
            elif task is checker_task:
                res_map['checker'] = res

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
            except Exception as e_task_pending:
                raise e_task_pending

        dropper_choice = res_map.get('dropper');
        checker_choice = res_map.get('checker')
        print(f"DEBUG run_game_flow: Task Results: Dropper_Choice={dropper_choice}, Checker_Choice={checker_choice}")

        if dropper_choice is None and active_duels.get(dropper.id, {}).get('game_state') == 'awaiting_numbers':
            if not exc_raised: raise PlayerTimedOutError(dropper)
        if checker_choice is None and active_duels.get(checker.id, {}).get('game_state') == 'awaiting_numbers':
            if not exc_raised: raise PlayerTimedOutError(checker)

    except (DMDisabledError, DMHttpError, PlayerTimedOutError, asyncio.CancelledError) as e_detail:
        reason = "DM/Timeout issue during number collection."  # Default
        # ... (same detailed reason setting as before) ...
        if isinstance(e_detail, DMDisabledError):
            reason = f"DM to {e_detail.player.mention} failed (likely disabled)."
        elif isinstance(e_detail, DMHttpError):
            reason = f"DM to {e_detail.player.mention} failed (HTTP error)."
        elif isinstance(e_detail, PlayerTimedOutError):
            p_data_timeout = active_duels.get(e_detail.player.id)
            if p_data_timeout and p_data_timeout.get('game_state') == 'awaiting_numbers':
                reason = f"{e_detail.player.mention} timed out."
            else:
                return
        elif isinstance(e_detail, asyncio.CancelledError):
            reason = "Game input collection was cancelled."
        print(f"DEBUG run_game_flow: Caught in DM block: {reason}")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      reason_channel_msg=f"{reason} Duel cancelled.");
        return  # Corrected keyword
    except Exception as e_unexpected:
        print(f"DEBUG run_game_flow: UNEXPECTED error in DM/number collection block: {e_unexpected}")
        traceback.print_exc()
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      reason_channel_msg="An unexpected game error occurred. Duel cancelled.");
        return  # Corrected keyword

    if not (active_duels.get(player1.id) and active_duels.get(player2.id)):
        print("DEBUG run_game_flow: Duel was cancelled during DM phase, not proceeding to results.");
        return
    if dropper_choice is None or checker_choice is None:
        print(
            f"DEBUG run_game_flow: ERROR - Numbers not collected prior to result. D:{dropper_choice} C:{checker_choice}. Cancelling.")
        await cancel_duel_and_cleanup(player1.id, player2.id, original_channel.id,
                                      reason_channel_msg="Internal error: numbers not collected. Duel cancelled.");
        return  # Corrected keyword

    game_winner_user = None;
    result_text = ""
    points_for_dropper_this_round = 0;
    points_for_checker_this_round = 0
    dropper_outcome = "tie";
    checker_outcome = "tie"

    if checker_choice > dropper_choice:
        game_winner_user = checker
        points_lost_by_dropper = checker_choice - dropper_choice
        result_text = f"Successful high check by Checker! {checker.mention} caught {dropper.mention}, who loses {points_lost_by_dropper} points."
        points_for_dropper_this_round = -points_lost_by_dropper
        points_for_checker_this_round = POINTS_PER_DUEL_WIN
        dropper_outcome = "loss";
        checker_outcome = "win"
    elif dropper_choice > checker_choice:
        game_winner_user = dropper
        result_text = f"Dropper outsmarted Checker! {dropper.mention} successfully dropped."
        points_for_dropper_this_round = POINTS_PER_DUEL_WIN
        dropper_outcome = "win";
        checker_outcome = "loss"
    else:
        result_text = "It's a tie! Numbers were equal."

    update_player_stats(guild_id, dropper, dropper_outcome, points_for_dropper_this_round)
    update_player_stats(guild_id, checker, checker_outcome, points_for_checker_this_round)

    dropper_current_stats = get_player_stats(guild_id, dropper.id)
    checker_current_stats = get_player_stats(guild_id, checker.id)

    res_lines = [
        "====𝐃𝐫𝐨𝐩 𝐓𝐡𝐞 𝐇𝐚𝐧𝐝𝐤𝐞𝐫𝐜𝐡𝐢𝐞𝐟====", f"Round {current_round_num}", " ~" * 15,
        f"{dropper.mention} Dropped: {dropper_choice}", f"{checker.mention} Checked: {checker_choice}", " ~" * 15,
        f"***RESULT: {result_text}***"
    ]
    if game_winner_user == dropper and points_for_dropper_this_round > 0:
        res_lines.append(f"{dropper.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_for_dropper_this_round} points this round**")
    elif game_winner_user == checker and points_for_checker_this_round > 0:
        res_lines.append(f"{checker.mention}: **A𝗰𝗰𝘂𝗺𝘂𝗹𝗮𝘁𝗲𝗱: {points_for_checker_this_round} points this round**")
    res_lines.extend([" ~" * 15, f"{dropper.mention} (Total: {dropper_current_stats['points']})",
                      f"{checker.mention} (Total: {checker_current_stats['points']})"])

    try:
        await original_channel.send("\n".join(res_lines))
    except Exception as e_send_res:
        print(f"Error sending result message to channel: {e_send_res}")
        dm_fallback_dropper = f"Game result: {result_text}. Your total points: {dropper_current_stats['points']}"
        dm_fallback_checker = f"Game result: {result_text}. Your total points: {checker_current_stats['points']}"
        try:
            await dropper.send(dm_fallback_dropper); await checker.send(dm_fallback_checker)  # Send to both
        except:
            pass  # Ignore if DMs fail here

    _clear_duel_data_for_user(player1.id);
    _clear_duel_data_for_user(player2.id)
    print(f"DEBUG run_game_flow: Game finished (New Rules Interpretation A) for P1:{player1.id}, P2:{player2.id}")


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
            print("!!! PRIVILEGED INTENTS REQUIRED: Enable Presence, Server Members, Message Content in Dev Portal.")
        except Exception as e:
            print(f"Unexpected error running bot: {e}"); traceback.print_exc()