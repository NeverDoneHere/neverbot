import discord
import asyncio
import datetime
import logging
from discord import app_commands
from discord.ext import commands


# Compatibility for discord.py versions with/without TextInputStyle
try:
    from discord.ui import TextInput, TextInputStyle
except ImportError:
    from discord.ui import TextInput
    from enum import IntEnum
    class TextInputStyle(IntEnum):
        short = 1
        paragraph = 2



class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # In-memory config for move permissions
        self.move_config = {
            'role_id': None,
            'channel_ids': set(),
            'category_ids': set(),
        }

    def is_mod(self, interaction):
        # Import here to avoid circular import
        from bot.utils.helpers import is_mod as global_is_mod
        return global_is_mod(interaction)

    @app_commands.command(name="vc_snapshot", description="Take a snapshot of users in a voice channel or all VCs in a category, now or after a timer.")
    async def vc_snapshot(self, interaction: discord.Interaction):
        await vc_snapshot_command(interaction)

    @app_commands.command(name="vc_disconnect_setup", description="Set up which VCs/categories and role can disconnect members.")
    async def vc_disconnect_setup(self, interaction: discord.Interaction):
        if not self.is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        view = MoveSetupView(interaction.guild)
        await interaction.response.send_message("Select VCs/categories and a role for disconnect permissions:", ephemeral=True, view=view)
        try:
            await interaction.client.tree.sync()
        except Exception as e:
            self.logger.warning(f"Failed to sync commands: {e}")

    @app_commands.context_menu(name="Disconnect Member")
    async def disconnect_member_context(self, interaction: discord.Interaction, target: discord.Member):
        if not self.move_config['role_id']:
            await interaction.response.send_message("Disconnect setup not configured.", ephemeral=True)
            return
        if self.move_config['role_id'] not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("You do not have the disconnect role.", ephemeral=True)
            return
        if not interaction.user.voice or not target.voice:
            await interaction.response.send_message("Both users must be in a voice channel.", ephemeral=True)
            return
        user_vc = interaction.user.voice.channel
        target_vc = target.voice.channel
        allowed = False
        if user_vc.id in self.move_config['channel_ids'] and user_vc.id == target_vc.id:
            allowed = True
        for cat_id in self.move_config['category_ids']:
            cat = interaction.guild.get_channel(cat_id)
            if cat and user_vc in cat.channels and user_vc == target_vc:
                allowed = True
        if not allowed:
            await interaction.response.send_message("You can only disconnect members in the same allowed VC.", ephemeral=True)
            return
        try:
            await target.edit(voice_channel=None)
            await interaction.response.send_message(f"✅ {target.display_name} has been disconnected from the voice channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to disconnect: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.content.startswith('!disconnect'):
            if not self.move_config['role_id']:
                await message.channel.send("Disconnect setup not configured.")
                return
            if self.move_config['role_id'] not in [role.id for role in message.author.roles]:
                await message.channel.send("You do not have the disconnect role.")
                return
            if not message.author.voice or not message.mentions:
                await message.channel.send("You and the mentioned user must both be in a voice channel.")
                return
            target = message.mentions[0]
            if not target.voice:
                await message.channel.send("The mentioned user is not in a voice channel.")
                return
            user_vc = message.author.voice.channel
            target_vc = target.voice.channel
            allowed = False
            if user_vc.id in self.move_config['channel_ids'] and user_vc.id == target_vc.id:
                allowed = True
            for cat_id in self.move_config['category_ids']:
                cat = message.guild.get_channel(cat_id)
                if cat and user_vc in cat.channels and user_vc == target_vc:
                    allowed = True
            if not allowed:
                await message.channel.send("You can only disconnect members in the same allowed VC.")
                return
            try:
                await target.edit(voice_channel=None)
                await message.channel.send(f"✅ {target.display_name} has been disconnected from the voice channel.")
            except Exception as e:
                await message.channel.send(f"❌ Failed to disconnect: {e}")

logger = logging.getLogger(__name__)

# --- VC SNAPSHOT WITH INTERACTION MENU, TIMER FEEDBACK, AND PUBLIC SNAPSHOT ---
async def vc_snapshot_command(interaction: discord.Interaction):
    logger.info("/vc_snapshot command invoked by %s (%s)", interaction.user, interaction.user.id)
    try:
        # Use the VoiceCog.is_mod method if available
        cog = interaction.client.get_cog("VoiceCog")
        if cog and hasattr(cog, "is_mod"):
            if not cog.is_mod(interaction):
                await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
                return
        else:
            # fallback (should not happen)
            from bot.utils.helpers import is_mod as global_is_mod
            if not global_is_mod(interaction):
                await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
                return

        class VCSnapshotTimerAndLimitModal(discord.ui.Modal, title="VC Snapshot: Timer & User Limit"):
            def __init__(self, channel, category, voice_channels):
                super().__init__()
                self.channel = channel
                self.category = category
                self.voice_channels = voice_channels
                self.timer_input = TextInput(
                    label="Timer (seconds, 0 = now, max 3600)",
                    style=TextInputStyle.short,
                    required=False,
                    default="0",
                    max_length=4
                )
                self.limit = TextInput(
                    label="User limit (0=unlimited, blank=skip)",
                    style=TextInputStyle.short,
                    required=False,
                    placeholder="0"
                )
                self.add_item(self.timer_input)
                self.add_item(self.limit)

            async def on_submit(self, interaction2: discord.Interaction):
                # Set user limit if provided
                if self.limit.value.strip() != "":
                    try:
                        limit = int(self.limit.value)
                        edited = 0
                        for vc in self.voice_channels:
                            await vc.edit(user_limit=limit)
                            edited += 1
                        # Don't send a message here, just proceed
                    except Exception as e:
                        await interaction2.response.send_message(
                            f"❌ Error setting user limit: {e}",
                            ephemeral=True
                        )
                        return
                # Handle timer and snapshot
                try:
                    timer = int(self.timer_input.value.strip() or "0")
                except Exception:
                    await interaction2.response.send_message("❌ Invalid timer value.", ephemeral=True)
                    return
                if timer < 0 or timer > 3600:
                    await interaction2.response.send_message("❌ Timer must be between 0 and 3600 seconds.", ephemeral=True)
                    return
                responded = False
                if self.channel:
                    target_desc = f"Voice Channel: **{self.channel.name}**"
                else:
                    target_desc = f"Category: **{self.category.name}**"
                if timer > 0:
                    await interaction2.response.send_message(
                        f"⏳ Timer started for {target_desc}. Snapshot will be posted in {timer} seconds...",
                        ephemeral=True
                    )
                    responded = True
                    await asyncio.sleep(timer)
                else:
                    await interaction2.response.defer(ephemeral=True, thinking=True)
                    responded = True
                if self.channel:
                    channels = [self.channel]
                    target_desc = f"Voice Channel: **{self.channel.name}**"
                else:
                    channels = [ch for ch in self.category.channels if isinstance(ch, discord.VoiceChannel)]
                    if not channels:
                        if responded:
                            await interaction2.followup.send(f"❌ No voice channels found in category '{self.category.name}'.", ephemeral=True)
                        else:
                            await interaction2.response.send_message(f"❌ No voice channels found in category '{self.category.name}'.", ephemeral=True)
                        return
                    target_desc = f"Category: **{self.category.name}** ({len(channels)} voice channels)"
                snapshot_lines = []
                total_users = 0
                for vc in channels:
                    members = [m for m in vc.members if not m.bot]
                    total_users += len(members)
                    if members:
                        user_list = ", ".join(discord.utils.escape_markdown(m.display_name) for m in members)
                        snapshot_lines.append(f"🔊 **{vc.name}** ({len(members)}): {user_list}")
                    else:
                        snapshot_lines.append(f"🔊 **{vc.name}**: *(empty)*")
                embed = discord.Embed(
                    title="🔎 VC Snapshot",
                    description=f"{target_desc}\nTimer: {timer} seconds\nTime: <t:{int(datetime.datetime.now().timestamp())}:f>",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name=f"Users Present ({total_users} total)",
                    value="\n".join(snapshot_lines)[:1024] if snapshot_lines else "No users found.",
                    inline=False
                )
                embed.set_footer(text=f"Requested by {interaction2.user.display_name}")
                try:
                    if interaction2.channel and isinstance(interaction2.channel, discord.TextChannel):
                        msg = await interaction2.channel.send(embed=embed, view=VCSnapshotView(channels))
                    else:
                        msg = await interaction2.user.send(embed=embed, view=VCSnapshotView(channels))
                except Exception as e:
                    logger.error(f"Failed to send snapshot: {e}")
                    if responded:
                        await interaction2.followup.send(f"❌ Failed to send snapshot: {e}", ephemeral=True)
                    else:
                        await interaction2.response.send_message(f"❌ Failed to send snapshot: {e}", ephemeral=True)
                    return
                try:
                    if responded:
                        await interaction2.followup.send("✅ VC snapshot posted!", ephemeral=True)
                    else:
                        await interaction2.response.send_message("✅ VC snapshot posted!", ephemeral=True)
                except Exception:
                    pass

        class VCOrCategorySelect(discord.ui.View):
            def __init__(self, guild):
                super().__init__(timeout=120)
                self.selected_channel = None
                self.selected_category = None
                self.guild = guild
                voice_channels = [ch for ch in guild.voice_channels]
                vc_options = [
                    discord.SelectOption(label=vc.name, value=f"vc:{vc.id}", description=f"Voice Channel")
                    for vc in voice_channels
                ]
                # Show all categories, even if empty, and allow selection
                categories = list(guild.categories)
                cat_options = [
                    discord.SelectOption(
                        label=cat.name,
                        value=f"cat:{cat.id}",
                        description=f"{len([ch for ch in cat.channels if isinstance(ch, discord.VoiceChannel)])} VCs"
                    )
                    for cat in categories
                ]
                options = vc_options + cat_options
                options = sorted(options, key=lambda o: o.label.lower())
                self.select = discord.ui.Select(
                    placeholder="Search and select a voice channel or category...",
                    min_values=1,
                    max_values=1,
                    options=options[:25]
                )
                self.select.callback = self.select_callback
                self.add_item(self.select)

            async def select_callback(self, interaction2: discord.Interaction):
                try:
                    value = self.select.values[0]
                    if value.startswith("vc:"):
                        self.selected_channel = self.guild.get_channel(int(value[3:]))
                        self.selected_category = None
                        channels = [self.selected_channel]
                        target_desc = f"Voice Channel: **{self.selected_channel.name}**"
                    elif value.startswith("cat:"):
                        self.selected_category = self.guild.get_channel(int(value[4:]))
                        self.selected_channel = None
                        # Allow empty categories to be selected, but show error if no VCs
                        channels = [ch for ch in self.selected_category.channels if isinstance(ch, discord.VoiceChannel)]
                        target_desc = f"Category: **{self.selected_category.name}** ({len(channels)} voice channels)"
                        if not channels:
                            await interaction2.response.send_message(f"❌ No voice channels found in category '{self.selected_category.name}'. You must add a voice channel to this category first.", ephemeral=True)
                            return
                    else:
                        await interaction2.response.send_message("❌ Invalid selection.", ephemeral=True)
                        return

                    # Show combined modal for timer and user limit
                    await interaction2.response.send_modal(VCSnapshotTimerAndLimitModal(
                        channels[0] if len(channels) == 1 else None,
                        self.selected_category if self.selected_category else None,
                        channels
                    ))
                except Exception as e:
                    logger.error(f"VCOrCategorySelect.select_callback error: {e}")
                    await interaction2.response.send_message(f"❌ Error: {e}", ephemeral=True)

        class VCSnapshotView(discord.ui.View):
            def __init__(self, voice_channels):
                super().__init__(timeout=300)
                self.voice_channels = voice_channels

            @discord.ui.button(label="Set User Limit for All", style=discord.ButtonStyle.primary)
            async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(SetLimitModal(self.voice_channels))

        class SetLimitModal(discord.ui.Modal, title="Set User Limit for All VCs"):
            def __init__(self, voice_channels):
                super().__init__()
                self.voice_channels = voice_channels
                self.limit = TextInput(
                    label="User limit (0 = unlimited)",
                    style=TextInputStyle.short,
                    required=True,
                    placeholder="0"
                )
                self.add_item(self.limit)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    limit = int(self.limit.value)
                    edited = 0
                    for vc in self.voice_channels:
                        await vc.edit(user_limit=limit)
                        edited += 1
                    await interaction.response.send_message(
                        f"✅ Set user limit to {limit} for {edited} voice channels.",
                        ephemeral=True
                    )
                except Exception as e:
                    await interaction.response.send_message(
                        f"❌ Error setting user limit: {e}",
                        ephemeral=True
                    )


        view = VCOrCategorySelect(interaction.guild)
        await interaction.response.send_message(
            "🔎 **VC Snapshot**\nSelect a voice channel or a category to snapshot:",
            ephemeral=True,
            view=view
        )
    except Exception as e:
        logger.error(f"/vc_snapshot top-level error: {e}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
        except Exception:
            pass

# In-memory config for move permissions
move_config = {
    'role_id': None,
    'channel_ids': set(),
    'category_ids': set(),
}

class MoveSetupView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=120)
        self.guild = guild
        # Voice channels
        voice_channels = [ch for ch in guild.voice_channels]
        vc_options = [
            discord.SelectOption(label=vc.name, value=f"vc:{vc.id}")
            for vc in voice_channels
        ]
        # All categories (not just those with VCs)
        categories = list(guild.categories)
        cat_options = [
            discord.SelectOption(label=cat.name, value=f"cat:{cat.id}")
            for cat in categories
        ]
        options = vc_options + cat_options
        self.channel_select = discord.ui.Select(
            placeholder="Select voice channels or categories...",
            min_values=1,
            max_values=min(25, len(options)),
            options=options[:25]
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)
        # Role select
        role_options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in guild.roles if not role.is_default()
        ]
        self.role_select = discord.ui.Select(
            placeholder="Select a role to grant disconnect power...",
            min_values=1,
            max_values=1,
            options=role_options[:25]
        )
        self.role_select.callback = self.role_callback
        self.add_item(self.role_select)
        self.selected_channels = set()
        self.selected_categories = set()
        self.selected_role = None


    async def channel_callback(self, interaction: discord.Interaction):
        self.selected_channels = set()
        self.selected_categories = set()
        for v in self.channel_select.values:
            if v.startswith("vc:"):
                self.selected_channels.add(int(v[3:]))
            elif v.startswith("cat:"):
                self.selected_categories.add(int(v[4:]))
        # Always defer the interaction to avoid double response errors
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)


    async def role_callback(self, interaction: discord.Interaction):
        self.selected_role = int(self.role_select.values[0])
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

    @discord.ui.button(label="Save Setup", style=discord.ButtonStyle.success)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role or (not self.selected_channels and not self.selected_categories):
            await interaction.response.send_message("Please select at least one channel/category and a role.", ephemeral=True)
            return
        move_config['role_id'] = self.selected_role
        move_config['channel_ids'] = self.selected_channels
        move_config['category_ids'] = self.selected_categories
        await interaction.response.send_message("✅ Disconnect setup saved!", ephemeral=True)

# Slash command for setup
def setup_vc_move(bot):
    # This function is now obsolete and replaced by the VoiceCog class method.
    return

    # Context menu for disconnecting members (global registration)
    @bot.tree.context_menu(name="Disconnect Member")
    async def disconnect_member_context(interaction: discord.Interaction, target: discord.Member):
        # Only allow if config is set
        if not move_config['role_id']:
            await interaction.response.send_message("Disconnect setup not configured.", ephemeral=True)
            return
        # Only allow if invoker has the role
        if move_config['role_id'] not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("You do not have the disconnect role.", ephemeral=True)
            return
        # Both must be in a voice channel
        if not interaction.user.voice or not target.voice:
            await interaction.response.send_message("Both users must be in a voice channel.", ephemeral=True)
            return
        user_vc = interaction.user.voice.channel
        target_vc = target.voice.channel
        allowed = False
        # If the user's VC is in the allowed channels, they can disconnect anyone (with any role) in that same VC, but not from other VCs
        if user_vc.id in move_config['channel_ids'] and user_vc.id == target_vc.id:
            allowed = True
        # If the user's VC is in an allowed category, they can disconnect anyone (with any role) in the same VC, but not from other VCs in the category
        for cat_id in move_config['category_ids']:
            cat = interaction.guild.get_channel(cat_id)
            if cat and user_vc in cat.channels and user_vc == target_vc:
                allowed = True
        if not allowed:
            await interaction.response.send_message("You can only disconnect members in the same allowed VC.", ephemeral=True)
            return
        # Disconnect the target from VC
        try:
            await target.edit(voice_channel=None)
            await interaction.response.send_message(f"✅ {target.display_name} has been disconnected from the voice channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to disconnect: {e}", ephemeral=True)
    # (Global sync is handled in on_ready in your main bot file. Do not sync here.)

    # --- NEW: Text command for disconnecting a user by mention ---
    @bot.event
    async def on_message(message):
        if message.author.bot:
            return
        if message.content.startswith('!disconnect'):
            if not move_config['role_id']:
                await message.channel.send("Disconnect setup not configured.")
                return
            if move_config['role_id'] not in [role.id for role in message.author.roles]:
                await message.channel.send("You do not have the disconnect role.")
                return
            if not message.author.voice or not message.mentions:
                await message.channel.send("You and the mentioned user must both be in a voice channel.")
                return
            target = message.mentions[0]
            if not target.voice:
                await message.channel.send("The mentioned user is not in a voice channel.")
                return
            user_vc = message.author.voice.channel
            target_vc = target.voice.channel
            allowed = False
            if user_vc.id in move_config['channel_ids'] and user_vc.id == target_vc.id:
                allowed = True
            for cat_id in move_config['category_ids']:
                cat = message.guild.get_channel(cat_id)
                if cat and user_vc in cat.channels and user_vc == target_vc:
                    allowed = True
            if not allowed:
                await message.channel.send("You can only disconnect members in the same allowed VC.")
                return
            try:
                await target.edit(voice_channel=None)
                await message.channel.send(f"✅ {target.display_name} has been disconnected from the voice channel.")
            except Exception as e:
                await message.channel.send(f"❌ Failed to disconnect: {e}")
async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
    await bot.add_cog(VoiceCog(bot))
