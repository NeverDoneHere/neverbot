# --- Ensure project root is in sys.path for cog imports ---
import sys
import os
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import json
import re
import random
import matplotlib.pyplot as plt
import numpy as np
import io
import imageio
import asyncio
import time
import logging
import warnings
from discord.utils import get as discord_get


# Suppress PyNaCl warning since we don't use voice features
warnings.filterwarnings("ignore", category=UserWarning, message=".*PyNaCl.*")
warnings.filterwarnings("ignore", message=".*PyNaCl.*")

# Set up logging to help debug issues
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress discord.py logger warnings about PyNaCl
logging.getLogger('discord.client').setLevel(logging.ERROR)

# --- Wheel Spinner Utility ---
def spin_wheel(options):
    num_options = len(options)
    if num_options < 2:
        raise ValueError("You need at least two options.")

    winner_idx = random.randint(0, num_options - 1)
    purples = plt.cm.Purples(np.linspace(0.4, 0.9, num_options))
    images = []
    spin_frames = 30
    # Calculate the angle so the winner ends at the top (12 o'clock, 90 deg)
    winner_angle = 360 * (winner_idx / num_options)
    final_startangle = 90 - winner_angle
    # Add extra spins for effect
    total_spin = 3 * 360  # 3 full spins
    
    try:
        for frame in range(spin_frames):
            # Interpolate the angle for smooth spinning
            progress = frame / (spin_frames - 1)
            angle = final_startangle + (1 - progress) * total_spin
            fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(aspect="equal"))
            discord_grey = '#2b2d31'  # Discord dark theme background
            fig.patch.set_facecolor(discord_grey)  # Set figure background to Discord grey
            ax.set_facecolor('black')         # Set axes background to black
            wedges, _ = ax.pie([1]*num_options, colors=purples, startangle=angle, counterclock=False)
            # Highlight the winner slice only on the last frame
            if frame == spin_frames - 1:
                wedges[winner_idx].set_edgecolor("black")
                wedges[winner_idx].set_linewidth(3)
            for i, wedge in enumerate(wedges):
                ang = (wedge.theta2 + wedge.theta1) / 2
                x = 0.7 * np.cos(np.deg2rad(ang))
                y = 0.7 * np.sin(np.deg2rad(ang))
                ax.text(x, y, options[i], ha='center', va='center', fontsize=12, color='white', weight='bold')
            # Arrow and annotation removed for a cleaner look
            plt.title("Spinning the Wheel..." if frame < spin_frames - 1 else f"Wheel Spin Result: {options[winner_idx]}", fontsize=16, color='white')
            # Remove axes for a cleaner look
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            buf = io.BytesIO()
            # Use the Discord grey as the facecolor for the saved image
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor=discord_grey)
            buf.seek(0)
            images.append(imageio.v2.imread(buf))
            plt.close(fig)  # Ensure figure is closed to free memory
            
    except Exception as e:
        # Clean up any remaining figures
        plt.close('all')
        raise e
    
    # Save as GIF
    gif_bytes = io.BytesIO()
    try:
        imageio.mimsave(gif_bytes, images, format='GIF', duration=0.06)
        gif_bytes.seek(0)
        return gif_bytes, options[winner_idx]
    except Exception as e:
        logger.error(f"Error creating GIF: {e}")
        raise e

# Setup constants
DISCORD_EPOCH = 1420070400000

# Convert snowflake to timestamp
def get_time_from_snowflake(snowflake: int) -> datetime.datetime:
    timestamp_ms = (snowflake >> 22) + DISCORD_EPOCH
    return datetime.datetime.utcfromtimestamp(timestamp_ms / 1000)

# Set up bot with all intents and slash command prefix for best compatibility
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="/", intents=intents)

# Suppress CommandNotFound errors in logs
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Optionally, you can send a message to the user here if you want
        return
    raise error  # Re-raise other errors

# Add connection monitoring
@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord")

@bot.event
async def on_resumed():
    logger.info("Bot connection resumed")

@bot.event
async def on_connect():
    logger.info("Bot connected to Discord")

# Add better error handling for connection issues
@bot.event
async def on_error(event, *args, **kwargs):
    logger.error(f"Unexpected error in {event}: {args}, {kwargs}")
    import traceback
    traceback.print_exc()

# Global error handler for app commands (slash commands)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"App command error: {error}")
    import traceback
    traceback.print_exc()
    try:
        # Only send error if not already responded
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}")

# Decorator for robust error handling in commands
import functools
def robust_command_handler(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in command {func.__name__}: {e}")
            import traceback
            traceback.print_exc()
            # Try to send error to user if possible
            interaction = args[0] if args else None
            if interaction and hasattr(interaction, 'response'):
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(f"❌ An error occurred: {e}", ephemeral=True)
                    else:
                        await interaction.followup.send(f"❌ An error occurred: {e}", ephemeral=True)
                except Exception as e2:
                    logger.error(f"Failed to send error message to user: {e2}")
    return wrapper

# Add shard ready event for better connection tracking
@bot.event
async def on_shard_ready(shard_id):
    logger.info(f"Shard {shard_id} is ready")

# Add shard disconnect tracking
@bot.event
async def on_shard_disconnect(shard_id):
    logger.warning(f"Shard {shard_id} disconnected")

# Add shard reconnect tracking
@bot.event
async def on_shard_resumed(shard_id):
    logger.info(f"Shard {shard_id} resumed")

# Configuration for moderator role (persistent)
MODROLE_FILE = "modrole.json"
mod_role_id = None
def load_mod_role():
    global mod_role_id
    if os.path.exists(MODROLE_FILE):
        try:
            with open(MODROLE_FILE, "r") as f:
                data = json.load(f)
                mod_role_id = data.get("mod_role_id")
        except Exception:
            mod_role_id = None
    else:
        mod_role_id = None
load_mod_role()


# Store scoreboard data with cleanup
scoreboards = {}



def create_scoreboard_embed(sb):
    embed = discord.Embed(title="📊 Scoreboard", color=discord.Color.blue())
    
    if sb['type'] == 'points':
        # Sort by points for display based on what's best
        reverse_sort = sb.get('points_best', 'highest') == 'highest'
        sorted_teams = sorted(sb['data'].items(), key=lambda x: x[1], reverse=reverse_sort)
        for team, score in sorted_teams:
            embed.add_field(name=team, value=f"{score} points", inline=False)
    else:  # elimination
        active_teams = [(team, status) for team, status in sb['data'].items() if status == 'Active']
        eliminated_teams = [(team, status) for team, status in sb['data'].items() if status == 'Eliminated']
        
        # Show active teams first
        for team, status in active_teams:
            embed.add_field(name=f"✅ {team}", value=status, inline=False)
        
        # Then show eliminated teams
        for team, status in eliminated_teams:
            embed.add_field(name=f"💀 {team}", value=status, inline=False)
    
    footer_text = f"Game Type: {sb['type'].title()}"
    if sb['type'] == 'points':
        footer_text += f" | {sb.get('points_best', 'highest').title()} wins"
    embed.set_footer(text=footer_text)
    return embed

# Check if user has mod role or administrator
def is_mod(interaction: discord.Interaction) -> bool:
    # Check if user is server owner
    if interaction.guild and interaction.user.id == interaction.guild.owner_id:
        return True
    
    # Check if user has administrator permissions
    try:
        if interaction.user.guild_permissions.administrator:
            return True
    except Exception:
        pass
    
    # Check if mod role is set and user has it
    if mod_role_id is None:
        return False
    
    # Support both Role objects and IDs in interaction.user.roles
    try:
        user_role_ids = [role.id if hasattr(role, 'id') else role for role in getattr(interaction.user, 'roles', [])]
        return mod_role_id in user_role_ids
    except Exception:
        return False

# Improve the ready event with better error handling
@bot.event
async def on_ready():
    print("on_ready event fired!")  # Add this line for debug
    try:
        load_mod_role()
        # Start auto-cleanup task
        async def auto_cleanup():
            """Periodic cleanup task"""
            while True:
                try:
                    # If you have a cleanup_old_data function, call it here
                    if 'cleanup_old_data' in globals():
                        # Cleanup old vote and scoreboard data older than 24 hours
                        def cleanup_old_data():
                            now = time.time()
                            # Clean up scoreboards older than 24 hours
                            to_delete_scoreboards = [cid for cid, sb in scoreboards.items() if sb and 'created_at' in sb and now - sb['created_at'] > 86400]
                            for cid in to_delete_scoreboards:
                                del scoreboards[cid]
                        cleanup_old_data()
                    await asyncio.sleep(3600)  # Run every hour
                except Exception as e:
                    logger.error(f"Cleanup task error: {e}")
                    await asyncio.sleep(3600)
        bot.loop.create_task(auto_cleanup())
        bot.loop.create_task(heartbeat_monitor())
        await bot.wait_until_ready()
        # --- Per-guild sync for instant slash command updates (replace with your guild ID) ---
        GUILD_ID = int(os.environ.get("TEST_GUILD_ID", "0"))
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            await bot.tree.sync(guild=guild)
            print(f"Synced commands to {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("Synced global commands")
        logger.info(f'✅ Logged in as {bot.user.name}')
        print(f'✅ Logged in as {bot.user.name}')
    except Exception as e:
        logger.error(f"Error in on_ready: {e}")
        print(f"Error in on_ready: {e}")
        # Don't crash, try to continue

# Add heartbeat monitoring
async def heartbeat_monitor():
    """Monitor bot connection and log heartbeat info"""
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            if bot.latency > 5.0:  # High latency warning
                logger.warning(f"High latency detected: {bot.latency:.2f}s")
            else:
                logger.info(f"Heartbeat OK: {bot.latency:.2f}s latency")
        except Exception as e:
            logger.error(f"Heartbeat monitor error: {e}")
            await asyncio.sleep(300)

# Command to set the moderator role


@bot.tree.command(name="setmodrole", description="Set the role allowed to use bot commands.")
@app_commands.describe(role="The role to be set as moderator")
async def setmodrole(interaction: discord.Interaction, role: discord.Role):
    global mod_role_id
    mod_role_id = role.id
    try:
        with open(MODROLE_FILE, "w") as f:
            json.dump({"mod_role_id": mod_role_id}, f)
        await interaction.response.send_message(
            f"✅ Moderator role set to `{role.name}` and saved.", ephemeral=True
        )
    except Exception as e:
        # Only send a response if not already responded
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"⚠️ Failed to save moderator role: {e}", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"⚠️ Failed to save moderator role: {e}", ephemeral=True
            )


# /broadcastembed command
@bot.tree.command(name="broadcastembed", description="Send a custom embed message to all channels in a category.")
async def broadcastembed(interaction: discord.Interaction):
    if not is_mod(interaction):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    class CategorySelectionView(discord.ui.View):
        def __init__(self, interaction):
            super().__init__(timeout=300)
            self.selected_category = None
            self.interaction = interaction
            categories = interaction.guild.categories
            if not categories:
                self.category_select = None
                return
            category_options = [
                discord.SelectOption(
                    label=category.name,
                    value=str(category.id),
                    description=f"{len(category.channels)} channels"
                ) for category in categories
            ]
            if category_options:
                self.category_select = discord.ui.Select(
                    placeholder="Select a category to broadcast to...",
                    options=category_options[:25],
                    min_values=1,
                    max_values=1
                )
                self.category_select.callback = self.category_callback
                self.add_item(self.category_select)
            else:
                self.category_select = None

        async def category_callback(self, interaction2: discord.Interaction):
            self.selected_category = interaction2.data['values'][0]
            category = self.interaction.guild.get_channel(int(self.selected_category))
            if category:
                text_channels = [ch for ch in category.channels if isinstance(ch, discord.TextChannel)]
                modal = BroadcastEmbedModal(self.selected_category, self.interaction)
                await interaction2.response.send_modal(modal)
            else:
                await interaction2.response.send_message("❌ Category not found.", ephemeral=True)

    class BroadcastEmbedModal(discord.ui.Modal, title="Create Broadcast Embed"):
        def __init__(self, category_id, interaction):
            super().__init__()
            self.category_id = category_id
            self.interaction = interaction
            self.embed_title = discord.ui.TextInput(
                label="Embed Title",
                style=discord.TextStyle.short,
                required=True,
                max_length=256,
                placeholder="Enter the title for your embed..."
            )
            self.embed_description = discord.ui.TextInput(
                label="Embed Description/Message",
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=4000,
                placeholder="Enter your message content here. You can use emojis! 🎉"
            )
            self.embed_color = discord.ui.TextInput(
                label="Embed Color (optional)",
                style=discord.TextStyle.short,
                required=False,
                max_length=7,
                placeholder="blue, red, green, or hex #FF0000"
            )
            self.footer_text = discord.ui.TextInput(
                label="Footer Text (optional)",
                style=discord.TextStyle.short,
                required=False,
                max_length=2048,
                placeholder="Optional footer text..."
            )
            self.thumbnail_url = discord.ui.TextInput(
                label="Thumbnail URL (optional)",
                style=discord.TextStyle.short,
                required=False,
                max_length=500,
                placeholder="https://example.com/image.png"
            )
            self.add_item(self.embed_title)
            self.add_item(self.embed_description)
            self.add_item(self.embed_color)
            self.add_item(self.footer_text)
            self.add_item(self.thumbnail_url)

        async def on_submit(self, interaction2: discord.Interaction):
            try:
                category = self.interaction.guild.get_channel(int(self.category_id))
                if not category:
                    await interaction2.response.send_message("❌ Category not found.", ephemeral=True)
                    return
                text_channels = [ch for ch in category.channels if isinstance(ch, discord.TextChannel)]
                if not text_channels:
                    await interaction2.response.send_message("❌ No text channels found in this category.", ephemeral=True)
                    return
                embed = discord.Embed(
                    title=self.embed_title.value,
                    description=self.embed_description.value
                )
                if self.embed_color.value.strip():
                    color_value = self.embed_color.value.strip().lower()
                    if color_value == "blue":
                        embed.color = discord.Color.blue()
                    elif color_value == "red":
                        embed.color = discord.Color.red()
                    elif color_value == "green":
                        embed.color = discord.Color.green()
                    elif color_value == "purple":
                        embed.color = discord.Color.purple()
                    elif color_value == "orange":
                        embed.color = discord.Color.orange()
                    elif color_value == "gold":
                        embed.color = discord.Color.gold()
                    elif color_value.startswith("#"):
                        try:
                            embed.color = discord.Color(int(color_value[1:], 16))
                        except ValueError:
                            embed.color = discord.Color.blue()
                    else:
                        embed.color = discord.Color.blue()
                else:
                    embed.color = discord.Color.blue()
                if self.footer_text.value.strip():
                    embed.set_footer(text=self.footer_text.value.strip())
                if self.thumbnail_url.value.strip():
                    try:
                        embed.set_thumbnail(url=self.thumbnail_url.value.strip())
                    except:
                        pass
                await interaction2.response.send_message(
                    f"📡 **Broadcasting to {len(text_channels)} channels in '{category.name}'...**\n"
                    f"**Preview:**",
                    embed=embed,
                    ephemeral=True,
                    view=BroadcastConfirmView(embed, text_channels, category.name)
                )
            except Exception as e:
                await interaction2.response.send_message(f"❌ Error creating embed: {e}", ephemeral=True)

    class BroadcastConfirmView(discord.ui.View):
        def __init__(self, embed, channels, category_name):
            super().__init__(timeout=120)
            self.embed = embed
            self.channels = channels
            self.category_name = category_name

        @discord.ui.button(label="✅ Broadcast to Channels", style=discord.ButtonStyle.green)
        async def confirm_broadcast(self, interaction3: discord.Interaction, button: discord.ui.Button):
            await interaction3.response.defer(ephemeral=True)
            success_count = 0
            failed_channels = []
            for channel in self.channels:
                try:
                    await channel.send(embed=self.embed)
                    success_count += 1
                except discord.Forbidden:
                    failed_channels.append(f"{channel.name} (no permissions)")
                except Exception as e:
                    failed_channels.append(f"{channel.name} ({str(e)[:50]})")
            result_message = f"✅ **Broadcast Complete!**\n"
            result_message += f"📂 **Category:** {self.category_name}\n"
            result_message += f"✅ **Successful:** {success_count}/{len(self.channels)} channels\n"
            if failed_channels:
                result_message += f"❌ **Failed:** {len(failed_channels)} channels\n"
                if len(failed_channels) <= 10:
                    result_message += f"**Failed channels:** {', '.join(failed_channels)}"
                else:
                    result_message += f"**Failed channels:** {', '.join(failed_channels[:10])} and {len(failed_channels) - 10} more..."
            await interaction3.followup.send(result_message, ephemeral=True)


        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_broadcast(self, interaction3: discord.Interaction, button: discord.ui.Button):
            await interaction3.response.send_message("❌ Broadcast cancelled.", ephemeral=True)

    view = CategorySelectionView(interaction)
    if getattr(view, 'category_select', None):
        await interaction.response.send_message(
            "📡 **Broadcast Embed to Category**\n"
            "Select a category to broadcast your embed message to all text channels within it:",
            ephemeral=True,
            view=view
        )
    else:
        await interaction.response.send_message("❌ No categories found in this server.", ephemeral=True)

# --- Management command to clear and resync all slash commands (owner only) ---
@bot.tree.command(name="resyncslash", description="Clear and resync all slash commands (owner only)")
async def resyncslash(interaction: discord.Interaction):
    app = await bot.application_info()
    if interaction.user.id != app.owner.id:
        # Only send a response if it hasn't already been sent
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
        return
    try:
        await bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ All global slash commands cleared and resynced. Duplicates should be gone.", ephemeral=True)
        else:
            await interaction.followup.send("✅ All global slash commands cleared and resynced. Duplicates should be gone.", ephemeral=True)
        logger.info("All global slash commands cleared and resynced by owner command.")
    except Exception as e:
        # Only send a response if it hasn't already been sent
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Error during resync: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Error during resync: {e}", ephemeral=True)
        logger.error(f"Error during slash command resync: {e}")

# --- Load Cogs for Slash Commands ---
@bot.event
async def setup_hook():
    print("sys.path:", sys.path)
    print("cwd:", os.getcwd())
    # Use correct cog paths for cogs in bot/cogs/
    cog_list = [
        "bot.cogs.vote",
        "bot.cogs.admin",
        "bot.cogs.fun",
        "bot.cogs.scoreboard",
        "bot.cogs.utility",
        "bot.cogs.voice",
        "bot.cogs.vc_lock_cog",
        "bot.cogs.generate1on1s",
    ]
    for cog in cog_list:
        try:
            print(f"Loading cog: {cog}")
            if cog not in bot.extensions:
                await bot.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            else:
                logger.info(f"Cog already loaded: {cog}")
        except discord.app_commands.errors.CommandAlreadyRegistered as e:
            logger.error(f"Failed to load cog {cog}: Command already registered: {e}")
            print(f"Failed to load cog {cog}: Command already registered: {e}")
        except Exception as e:
            logger.error(f"Failed to load cog {cog}: {e}")
            print(f"Failed to load cog {cog}: {e}")

    # --- FAST GUILD SYNC FOR TESTING (replace GUILD_ID_HERE with your server's ID) ---
    try:
        GUILD_ID = int(os.environ.get("TEST_GUILD_ID", "0"))
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"Slash commands synced to guild {GUILD_ID}. {len(synced)} commands registered.")
            print(f"Slash commands synced to guild {GUILD_ID}. {len(synced)} commands registered.")
        elif os.environ.get("FORCE_GLOBAL_SYNC", "0") == "1":
            await bot.tree.sync()
            logger.info("Slash commands globally synced.")
        else:
            logger.info("Global sync skipped (set FORCE_GLOBAL_SYNC=1 to enable).")
    except Exception as e:
        logger.warning(f"Command sync failed: {e}")
        print(f"Command sync failed: {e}")

# --- ADD THIS TO THE VERY BOTTOM OF YOUR FILE TO RUN THE BOT ---
if __name__ == "__main__":
    # Hardcoded token (not recommended for production, but as requested)
    TOKEN = "INSERT TOKEN HERE"
    print("Starting Discord bot...")  # Add this line for debug
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        bot.run(TOKEN)
    except Exception as e:
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()
        traceback.print_exc()
        print(f"Failed to start bot: {e}")
        import traceback
        traceback.print_exc()


