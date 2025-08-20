import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import discord
from discord.ext import commands
from discord import app_commands

import re
import time
from bot.utils.helpers import is_mod, cleanup_old_data, active_votes, scoreboards, logger

# Store locked VC members (channel_id: [member_ids])
vc_locked_members = {}

# In-memory config for move permissions
move_config = {
    'role_id': None,
    'channel_ids': set(),
    'category_ids': set(),
}

class AdminCog(commands.Cog):
    """Admin and moderation commands (roles, channels, cleanup, etc.)"""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="changeroles", description="Interactive role manager for users and roles.")
    async def changeroles(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        class RoleActionView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)
                self.action = None
                self.action_select = discord.ui.Select(
                    placeholder="Select action (add, remove, or both)",
                    options=[
                        discord.SelectOption(label="Add Roles", value="add"),
                        discord.SelectOption(label="Remove Roles", value="remove"),
                        discord.SelectOption(label="Add & Remove Roles", value="both"),
                    ],
                    min_values=1, max_values=1
                )
                self.action_select.callback = self.action_callback
                self.add_item(self.action_select)

            async def action_callback(self, i2: discord.Interaction):
                self.action = self.action_select.values[0]
                await i2.response.send_modal(UserRoleModal(self.action))

        class UserRoleModal(discord.ui.Modal, title="Select Users and Roles"):
            def __init__(self, action):
                super().__init__()
                self.action = action
                self.user_ids = discord.ui.TextInput(
                    label="User IDs or @mentions (comma-separated)",
                    style=discord.TextStyle.paragraph,
                    required=True,
                    placeholder="e.g. 1234567890, @user1, @user2"
                )
                self.roles_to_add = discord.ui.TextInput(
                    label="Roles to Add (comma-separated, optional)",
                    style=discord.TextStyle.paragraph,
                    required=False,
                    placeholder="e.g. @role1, 9876543210"
                )
                self.roles_to_remove = discord.ui.TextInput(
                    label="Roles to Remove (comma-separated, optional)",
                    style=discord.TextStyle.paragraph,
                    required=False,
                    placeholder="e.g. @role2, 8765432109"
                )
                self.add_item(self.user_ids)
                if self.action in ("add", "both"):
                    self.add_item(self.roles_to_add)
                if self.action in ("remove", "both"):
                    self.add_item(self.roles_to_remove)

            async def on_submit(self, i3: discord.Interaction):
                guild = i3.guild
                # Parse users
                user_inputs = [u.strip() for u in self.user_ids.value.split(",") if u.strip()]
                members = set()
                for u in user_inputs:
                    if u.isdigit():
                        m = guild.get_member(int(u))
                        if m:
                            members.add(m)
                    elif u.startswith("<@") and u.endswith(">"):
                        uid = u.replace("<@", "").replace(">", "").replace("!", "")
                        if uid.isdigit():
                            m = guild.get_member(int(uid))
                            if m:
                                members.add(m)
                if not members:
                    await i3.response.send_message("❌ No valid users found.", ephemeral=True)
                    return
                # Parse roles
                roles_to_add = set()
                roles_to_remove = set()
                if self.action in ("add", "both") and self.roles_to_add.value:
                    for r in self.roles_to_add.value.split(","):
                        r = r.strip()
                        if r.isdigit():
                            role = guild.get_role(int(r))
                            if role:
                                roles_to_add.add(role)
                        elif r.startswith("<@&") and r.endswith(">"):
                            rid = r.replace("<@&", "").replace(">", "")
                            if rid.isdigit():
                                role = guild.get_role(int(rid))
                                if role:
                                    roles_to_add.add(role)
                        else:
                            role = discord.utils.get(guild.roles, name=r)
                            if role:
                                roles_to_add.add(role)
                if self.action in ("remove", "both") and self.roles_to_remove.value:
                    for r in self.roles_to_remove.value.split(","):
                        r = r.strip()
                        if r.isdigit():
                            role = guild.get_role(int(r))
                            if role:
                                roles_to_remove.add(role)
                        elif r.startswith("<@&") and r.endswith(">"):
                            rid = r.replace("<@&", "").replace(">", "")
                            if rid.isdigit():
                                role = guild.get_role(int(rid))
                                if role:
                                    roles_to_remove.add(role)
                        else:
                            role = discord.utils.get(guild.roles, name=r)
                            if role:
                                roles_to_remove.add(role)
                # Apply changes
                add_count = 0
                remove_count = 0
                failed = []
                for m in members:
                    try:
                        if self.action in ("add", "both") and roles_to_add:
                            for role in roles_to_add:
                                await m.add_roles(role, reason=f"Role manager via /changeroles by {i3.user}")
                                add_count += 1
                        if self.action in ("remove", "both") and roles_to_remove:
                            for role in roles_to_remove:
                                await m.remove_roles(role, reason=f"Role manager via /changeroles by {i3.user}")
                                remove_count += 1
                    except Exception as e:
                        failed.append(f"{m.display_name}: {e}")
                msg = f"✅ Role changes complete.\nUsers affected: {len(members)}\nRoles added: {add_count}\nRoles removed: {remove_count}"
                if failed:
                    msg += f"\n❌ Failed: {len(failed)}\n" + "\n".join(failed[:5])
                await i3.response.send_message(msg, ephemeral=True)

        await interaction.response.send_message(
            "Select what you want to do:",
            ephemeral=True,
            view=RoleActionView()
        )

    @app_commands.command(name="deletechannel", description="Delete all channels in a selected category (but not the category itself).")
    async def deletechannel(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        class CategorySelectionView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.selected_category = None
                categories = interaction.guild.categories
                if not categories:
                    return
                category_options = []
                for category in categories:
                    category_options.append(discord.SelectOption(
                        label=category.name,
                        value=str(category.id),
                        description=f"{len(category.channels)} channels to delete"
                    ))
                if category_options:
                    self.category_select = discord.ui.Select(
                        placeholder="Select a category to delete all channels from...",
                        options=category_options[:25],
                        min_values=1,
                        max_values=1
                    )
                    self.category_select.callback = self.category_callback
                    self.add_item(self.category_select)

            async def category_callback(self, interaction2: discord.Interaction):
                self.selected_category = interaction2.data['values'][0]
                category = interaction.guild.get_channel(int(self.selected_category))
                if category:
                    channels_to_delete = []
                    for ch in category.channels:
                        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel)) and not isinstance(ch, discord.CategoryChannel):
                            channels_to_delete.append(ch)
                    if not channels_to_delete:
                        await interaction2.response.send_message("❌ No channels found in this category.", ephemeral=True)
                        return
                    embed = discord.Embed(
                        title="⚠️ **DANGER: Channel Deletion**",
                        description=f"**Category:** {category.name}\n"
                                    f"**Channels to delete:** {len(channels_to_delete)}\n\n"
                                    f"**This action will:**\n"
                                    f"• Delete ALL {len(channels_to_delete)} channels in this category\n"
                                    f"• Keep the category '{category.name}' intact\n"
                                    f"• **PERMANENTLY** remove all messages and data\n\n"
                                    f"**⚠️ THIS CANNOT BE UNDONE!**",
                        color=discord.Color.red()
                    )
                    channel_list = []
                    for i, channel in enumerate(channels_to_delete[:10]):
                        channel_type = "🔊" if isinstance(channel, discord.VoiceChannel) else "💬"
                        channel_list.append(f"{channel_type} {channel.name}")
                    if len(channels_to_delete) > 10:
                        channel_list.append(f"... and {len(channels_to_delete) - 10} more")
                    embed.add_field(
                        name="Channels to Delete",
                        value="\n".join(channel_list),
                        inline=False
                    )
                    await interaction2.response.send_message(
                        embed=embed,
                        ephemeral=True,
                        view=DeleteConfirmView(category, channels_to_delete)
                    )
                else:
                    await interaction2.response.send_message("❌ Category not found.", ephemeral=True)

        class DeleteConfirmView(discord.ui.View):
            def __init__(self, category, channels_to_delete):
                super().__init__(timeout=120)
                self.category = category
                self.channels_to_delete = channels_to_delete

            @discord.ui.button(label="🗑️ DELETE ALL CHANNELS", style=discord.ButtonStyle.danger)
            async def confirm_delete(self, interaction3: discord.Interaction, button: discord.ui.Button):
                await interaction3.response.defer(ephemeral=True)
                deleted_count = 0
                failed_channels = []
                category_name = self.category.name
                category_id = self.category.id
                for channel in self.channels_to_delete:
                    try:
                        if isinstance(channel, discord.CategoryChannel):
                            failed_channels.append(f"{channel.name} (SAFETY: Category skipped)")
                            continue
                        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                            await channel.delete(reason=f"Mass deletion via deletechannel command by {interaction3.user}")
                            deleted_count += 1
                        else:
                            failed_channels.append(f"{channel.name} (unsupported channel type)")
                    except discord.Forbidden:
                        failed_channels.append(f"{channel.name} (no permissions)")
                    except discord.NotFound:
                        failed_channels.append(f"{channel.name} (already deleted)")
                    except Exception as e:
                        failed_channels.append(f"{channel.name} ({str(e)[:50]})")
                category_still_exists = interaction3.guild.get_channel(category_id) is not None
                result_message = f"🗑️ **Channel Deletion Complete!**\n\n"
                result_message += f"📂 **Category:** {category_name}\n"
                result_message += f"✅ **Deleted:** {deleted_count}/{len(self.channels_to_delete)} channels\n"
                if failed_channels:
                    result_message += f"\n❌ **Failed:** {len(failed_channels)} channels\n"
                    if len(failed_channels) <= 5:
                        result_message += f"**Failed channels:** {', '.join(failed_channels)}"
                    else:
                        result_message += f"**Failed channels:** {', '.join(failed_channels[:5])} and {len(failed_channels) - 5} more..."
                if category_still_exists:
                    result_message += f"\n\n✅ **Category '{category_name}' remains intact.**"
                else:
                    result_message += f"\n\n⚠️ **Category '{category_name}' was automatically removed by Discord (no channels remaining).**"
                await interaction3.followup.send(result_message, ephemeral=True)

            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel_delete(self, interaction3: discord.Interaction, button: discord.ui.Button):
                await interaction3.response.send_message("❌ Channel deletion cancelled. No channels were deleted.", ephemeral=True)

        view = CategorySelectionView()
        if hasattr(view, 'category_select'):
            await interaction.response.send_message(
                "🗑️ **Delete Channels in Category**\n"
                "⚠️ **WARNING:** This will delete ALL channels in the selected category!\n"
                "Select a category to proceed:",
                ephemeral=True,
                view=view
            )
        else:
            await interaction.response.send_message("❌ No categories found in this server.", ephemeral=True)

    @app_commands.command(name="eliminated", description="Remove all roles from users and assign a new role.")
    async def eliminated(self, interaction: discord.Interaction):
        await interaction.response.send_message("Eliminate feature coming soon!", ephemeral=True)

    @app_commands.command(name="eliminated_namechange", description="Remove all roles, set nickname, and assign a new role.")
    async def eliminated_namechange(self, interaction: discord.Interaction):
        await interaction.response.send_message("Eliminate & name change feature coming soon!", ephemeral=True)

    @app_commands.command(name="cleanup", description="Manually clean up old vote and scoreboard data (moderator only).")
    async def cleanup_data(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            old_votes = len(active_votes)
            old_scoreboards = len(scoreboards)
            cleanup_old_data()
            new_votes = len(active_votes)
            new_scoreboards = len(scoreboards)
            cleaned_votes = old_votes - new_votes
            cleaned_scoreboards = old_scoreboards - new_scoreboards
            embed = discord.Embed(
                title="🧹 Data Cleanup Complete",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Vote Data",
                value=f"**Before:** {old_votes}\n**After:** {new_votes}\n**Cleaned:** {cleaned_votes}",
                inline=True
            )
            embed.add_field(
                name="Scoreboard Data",
                value=f"**Before:** {old_scoreboards}\n**After:** {new_scoreboards}\n**Cleaned:** {cleaned_scoreboards}",
                inline=True
            )
            embed.add_field(
                name="Total Cleaned",
                value=f"{cleaned_votes + cleaned_scoreboards} items",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error during cleanup: {e}", ephemeral=True)
            logger.error(f"Manual cleanup error: {e}")

    @app_commands.command(name="sortcategory", description="Sort all text/voice channels in a category alphabetically.")
    async def sort_category(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        class CategorySelectionView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.selected_category = None
                categories = interaction.guild.categories
                if not categories:
                    return
                category_options = []
                for category in categories:
                    category_options.append(discord.SelectOption(label=category.name, value=str(category.id)))
                if category_options:
                    self.category_select = discord.ui.Select(
                        placeholder="Select a category...",
                        options=category_options,
                        min_values=1,
                        max_values=1
                    )
                    self.category_select.callback = self.category_callback
                    self.add_item(self.category_select)
            async def category_callback(self, interaction2: discord.Interaction):
                self.selected_category = interaction2.data['values'][0]
                category = interaction.guild.get_channel(int(self.selected_category))
                if category:
                    # ...existing code to sort channels...
                    pass
                else:
                    await interaction2.response.send_message("❌ Category not found.", ephemeral=True)
        view = CategorySelectionView()
        if hasattr(view, 'category_select'):
            await interaction.response.send_message(
                "📂 **Sort Channels in Category**\nSelect a category to sort all text and voice channels within it alphabetically:",
                ephemeral=True,
                view=view
            )
        else:
            await interaction.response.send_message("❌ No categories found in this server.", ephemeral=True)

class MoveCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="vc_move_setup", description="Set up which VCs/categories and role can move members.")
    async def vc_move_setup(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        view = self.MoveSetupView(interaction.guild)
        await interaction.response.send_message("Select VCs/categories and a role for move permissions:", ephemeral=True, view=view)

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
            # Categories with VCs
            categories = [cat for cat in guild.categories if any(isinstance(ch, discord.VoiceChannel) for ch in cat.channels)]
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
                placeholder="Select a role to grant move power...",
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
            await interaction.response.send_message(f"Selected channels/categories updated.", ephemeral=True, delete_after=1)

        async def role_callback(self, interaction: discord.Interaction):
            self.selected_role = int(self.role_select.values[0])
            await interaction.response.send_message(f"Selected role updated.", ephemeral=True, delete_after=1)

        @discord.ui.button(label="Save Setup", style=discord.ButtonStyle.success)
        async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self.selected_role or (not self.selected_channels and not self.selected_categories):
                await interaction.response.send_message("Please select at least one channel/category and a role.", ephemeral=True)
                return
            move_config['role_id'] = self.selected_role
            move_config['channel_ids'] = self.selected_channels
            move_config['category_ids'] = self.selected_categories
            await interaction.response.send_message("✅ Move setup saved!", ephemeral=True)

# Move Member context menu command (must be at module level)
@app_commands.context_menu(name="Move Member")
async def move_member_context(interaction: discord.Interaction, target: discord.Member):
    if not move_config['role_id']:
        await interaction.response.send_message("Move setup not configured.", ephemeral=True)
        return
    if move_config['role_id'] not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("You do not have the move role.", ephemeral=True)
        return
    if not interaction.user.voice or not target.voice:
        await interaction.response.send_message("Both users must be in a voice channel.", ephemeral=True)
        return
    user_vc = interaction.user.voice.channel
    target_vc = target.voice.channel
    allowed = False
    if user_vc.id in move_config['channel_ids']:
        allowed = user_vc.id == target_vc.id
    for cat_id in move_config['category_ids']:
        cat = interaction.guild.get_channel(cat_id)
        if cat and user_vc in cat.channels and user_vc == target_vc:
            allowed = True
    if not allowed:
        await interaction.response.send_message("You can only move members in the same allowed VC.", ephemeral=True)
        return
    dest_vcs = [vc for vc in interaction.guild.voice_channels if vc != user_vc]
    if not dest_vcs:
        await interaction.response.send_message("No other voice channels to move to.", ephemeral=True)
        return
    class DestVCSelect(discord.ui.View):
        def __init__(self, vcs):
            super().__init__(timeout=30)
            options = [discord.SelectOption(label=vc.name, value=str(vc.id)) for vc in vcs]
            self.select = discord.ui.Select(placeholder="Select destination VC...", options=options)
            self.select.callback = self.select_callback
            self.add_item(self.select)
            self.selected = None
        async def select_callback(self, i2):
            self.selected = int(self.select.values[0])
            await i2.response.defer()
            self.stop()
    view = DestVCSelect(dest_vcs)
    await interaction.response.send_message("Select a destination VC to move the member:", ephemeral=True, view=view)
    timeout = await view.wait()
    if view.selected:
        try:
            await target.move_to(interaction.guild.get_channel(view.selected))
            await interaction.followup.send(f"✅ Moved {target.display_name} to <#{view.selected}>.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to move: {e}", ephemeral=True)
    else:
        await interaction.followup.send("Move cancelled or timed out.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
