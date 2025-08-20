# ...existing imports...
import re
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
# Import mod_role_id from your main bot file
try:
    from backupeverbot import mod_role_id
except ImportError:
    mod_role_id = None


class Generate1on1s(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="generate1on1s", description="Generate 1-on-1 channels between selected roles in selected categories.")
    async def generate1on1s(self, ctx):
        interaction = ctx.interaction if hasattr(ctx, "interaction") else ctx
        # Permission check (replace with your own is_mod logic if needed)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.name != "@everyone"]
        if not roles:
            await interaction.response.send_message("❌ No suitable roles found in this server.", ephemeral=True)
            return

        roles.sort(key=lambda x: x.name.lower())
        # Add mod role toggle option to setup view
        view = Generate1on1SetupView(roles, interaction.guild)
        embed = discord.Embed(
            title="🎯 Generate 1-on-1 Channels Setup",
            description="**Step 1:** Click the button below to select roles for 1-on-1 channel creation.\n\n"
                        "**Quick Select**: Pick a single role to create channels with selected other roles\n\n"
                        "**Mod Role Option:** Use the toggle below to add the mod role to all created channels.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class Generate1on1SetupView(discord.ui.View):
    def __init__(self, roles, guild):
        super().__init__(timeout=300)
        self.roles = roles
        self.guild = guild
        self.add_mod_role = False
        # Add a toggle button for mod role
        self.mod_role_toggle = discord.ui.Button(
            label="Add Mod Role to Channels: OFF",
            style=discord.ButtonStyle.secondary,
            row=1
        )
        self.mod_role_toggle.callback = self.toggle_mod_role
        self.add_item(self.mod_role_toggle)

    async def toggle_mod_role(self, interaction: discord.Interaction):
        self.add_mod_role = not self.add_mod_role
        self.mod_role_toggle.label = f"Add Mod Role to Channels: {'ON' if self.add_mod_role else 'OFF'}"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="🎯 Quick Select (1 vs Selected)", style=discord.ButtonStyle.primary, row=0)
    async def quick_select(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Pass add_mod_role state to next view
        view = QuickSelectView(self.roles, self.guild, add_mod_role=self.add_mod_role)
        embed = discord.Embed(
            title="🎯 Quick Select Mode",
            description="Select **one main role** and then **select which other roles** to create 1-on-1 channels with.\n\n"
                        "Perfect for creating channels between one main role and specific other roles.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=view)

class QuickSelectView(discord.ui.View):
    def __init__(self, roles, guild, add_mod_role=False):
        super().__init__(timeout=300)
        self.roles = roles
        self.guild = guild
        self.selected_role = None
        self.selected_other_roles = []
        self.current_page = 0
        self.main_page = 0
        self.roles_per_page = 20
        self.user = None
        self.add_mod_role = add_mod_role
        self.update_dropdown()

    def update_dropdown(self):
        self.clear_items()
        start_idx = self.main_page * self.roles_per_page
        end_idx = start_idx + self.roles_per_page
        current_main_roles = self.roles[start_idx:end_idx]
        main_select = discord.ui.Select(
            placeholder=f"Select one main role... (Page {self.main_page + 1}/{((len(self.roles) - 1) // self.roles_per_page) + 1})",
            min_values=1,
            max_values=1,
            row=0
        )
        for role in current_main_roles:
            main_select.add_option(label=f"MAIN: {role.name}", value=str(role.id))
        main_select.callback = self.main_role_select_callback
        self.add_item(main_select)
        if len(self.roles) > self.roles_per_page:
            if self.main_page > 0:
                prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=1)
                prev_btn.callback = self.prev_main_page
                self.add_item(prev_btn)
            if (self.main_page + 1) * self.roles_per_page < len(self.roles):
                next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
                next_btn.callback = self.next_main_page
                self.add_item(next_btn)
        if self.selected_role:
            continue_btn = discord.ui.Button(label="Continue to Target Roles", style=discord.ButtonStyle.success, row=2)
            continue_btn.callback = self.continue_to_targets
            self.add_item(continue_btn)

    async def prev_main_page(self, interaction: discord.Interaction):
        self.main_page = max(0, self.main_page - 1)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def next_main_page(self, interaction: discord.Interaction):
        max_page = (len(self.roles) - 1) // self.roles_per_page
        self.main_page = min(max_page, self.main_page + 1)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def main_role_select_callback(self, interaction: discord.Interaction):
        role_id = int(interaction.data['values'][0])
        self.selected_role = self.guild.get_role(role_id)
        self.selected_other_roles = []
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def continue_to_targets(self, interaction: discord.Interaction):
        other_roles = [r for r in self.roles if r != self.selected_role]
        view = TargetRoleSelectionView(self.selected_role, other_roles, self.guild, add_mod_role=self.add_mod_role)
        embed = discord.Embed(
            title="🎯 Select Target Roles",
            description=f"**Main Role:** {self.selected_role.name}\n\n"
                        f"Select which roles to create 1-on-1 channels with:",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)

class TargetRoleSelectionView(discord.ui.View):
    def __init__(self, main_role, other_roles, guild, add_mod_role=False):
        super().__init__(timeout=300)
        self.main_role = main_role
        self.other_roles = other_roles
        self.guild = guild
        self.selected_target_roles = []
        self.current_page = 0
        self.roles_per_page = 20
        self.user = None
        self.add_mod_role = add_mod_role
        self.update_dropdown()

    def update_dropdown(self):
        self.clear_items()
        start_idx = self.current_page * self.roles_per_page
        end_idx = start_idx + self.roles_per_page
        current_roles = self.other_roles[start_idx:end_idx]
        role_select = discord.ui.Select(
            placeholder=f"Select target roles... (Page {self.current_page + 1}/{((len(self.other_roles) - 1) // self.roles_per_page) + 1})",
            min_values=0,
            max_values=len(current_roles),
            row=0
        )
        for role in current_roles:
            is_selected = role in self.selected_target_roles
            role_select.add_option(
                label=f"{'✅ ' if is_selected else ''}{role.name}",
                value=str(role.id),
                default=is_selected
            )
        role_select.callback = self.role_select_callback
        self.add_item(role_select)
        select_all_btn = discord.ui.Button(
            label="Select All on Page",
            style=discord.ButtonStyle.secondary,
            row=1
        )
        select_all_btn.callback = self.select_all_callback
        self.add_item(select_all_btn)
        if len(self.other_roles) > self.roles_per_page:
            if self.current_page > 0:
                prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=2)
                prev_btn.callback = self.prev_page
                self.add_item(prev_btn)
            if (self.current_page + 1) * self.roles_per_page < len(self.other_roles):
                next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=2)
                next_btn.callback = self.next_page
                self.add_item(next_btn)
        if self.selected_target_roles:
            continue_btn = discord.ui.Button(
                label=f"Continue to Categories ({len(self.selected_target_roles)} selected)",
                style=discord.ButtonStyle.success,
                row=3
            )
            continue_btn.callback = self.continue_to_categories
            self.add_item(continue_btn)

    async def role_select_callback(self, interaction: discord.Interaction):
        if self.user is None:
            self.user = interaction.user
        elif interaction.user != self.user:
            await interaction.response.send_message("❌ Only the command user can select roles.", ephemeral=True)
            return
        selected_ids = [int(role_id) for role_id in interaction.data['values']]
        start_idx = self.current_page * self.roles_per_page
        end_idx = start_idx + self.roles_per_page
        current_roles = self.other_roles[start_idx:end_idx]
        self.selected_target_roles = [r for r in self.selected_target_roles if r not in current_roles]
        for role_id in selected_ids:
            role = self.guild.get_role(role_id)
            if role and role not in self.selected_target_roles:
                self.selected_target_roles.append(role)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def select_all_callback(self, interaction: discord.Interaction):
        if self.user is None:
            self.user = interaction.user
        elif interaction.user != self.user:
            await interaction.response.send_message("❌ Only the command user can select roles.", ephemeral=True)
            return
        start_idx = self.current_page * self.roles_per_page
        end_idx = start_idx + self.roles_per_page
        current_roles = self.other_roles[start_idx:end_idx]
        for role in current_roles:
            if role not in self.selected_target_roles:
                self.selected_target_roles.append(role)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        max_page = (len(self.other_roles) - 1) // self.roles_per_page
        self.current_page = min(max_page, self.current_page + 1)
        self.update_dropdown()
        await interaction.response.edit_message(view=self)

    async def continue_to_categories(self, interaction: discord.Interaction):
        if interaction.user != self.user:
            await interaction.response.send_message("❌ Only the command user can continue.", ephemeral=True)
            return
        categories = interaction.guild.categories
        if not categories:
            await interaction.response.send_message("❌ No categories found in this server.", ephemeral=True)
            return
        view = CategorySelectionView(self.main_role, self.selected_target_roles, categories, self.guild, add_mod_role=self.add_mod_role)
        embed = discord.Embed(
            title="📂 Select Categories",
            description=f"Select categories where you want to create 1-on-1 channels.\n\n"
                        f"**Main Role:** {self.main_role.name}\n"
                        f"**Target Roles:** {len(self.selected_target_roles)} selected\n"
                        f"**Channels per category:** {len(self.selected_target_roles)}\n\n"
                        f"💡 **Tip:** Empty categories work perfectly for organizing new competition channels!",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=view)

class CategorySelectionView(discord.ui.View):
    def __init__(self, main_role, target_roles, categories, guild, add_mod_role=False):
        super().__init__(timeout=300)
        self.main_role = main_role
        self.target_roles = target_roles
        self.categories = categories
        self.guild = guild
        self.selected_categories = []
        self.user = None
        self.add_mod_role = add_mod_role
        category_options = []
        for category in categories[:25]:
            channel_count = len(category.channels)
            category_options.append(discord.SelectOption(
                label=category.name,
                value=str(category.id),
                description=f"{channel_count} existing channels" if channel_count > 0 else "Empty category (perfect for new channels!)"
            ))
        if category_options:
            category_select = discord.ui.Select(
                placeholder="Select categories for channel creation...",
                options=category_options,
                min_values=1,
                max_values=len(category_options)
            )
            category_select.callback = self.category_callback
            self.add_item(category_select)
        create_btn = discord.ui.Button(
            label="Create 1-on-1 Channels",
            style=discord.ButtonStyle.success,
            disabled=True
        )
        create_btn.callback = self.create_channels_callback
        self.add_item(create_btn)
        self.create_btn = create_btn

    async def category_callback(self, interaction2: discord.Interaction):
        if self.user is None:
            self.user = interaction2.user
        elif interaction2.user != self.user:
            await interaction2.response.send_message("❌ Only the command user can select categories.", ephemeral=True)
            return
        selected_ids = [int(cat_id) for cat_id in interaction2.data['values']]
        self.selected_categories = [self.guild.get_channel(cat_id) for cat_id in selected_ids]
        self.selected_categories = [cat for cat in self.selected_categories if cat is not None]
        self.create_btn.disabled = False
        category_info = []
        for cat in self.selected_categories:
            existing_count = len(cat.channels)
            category_info.append(f"📂 **{cat.name}** ({existing_count} existing)")
        embed = discord.Embed(
            title="📂 Categories Selected",
            description=f"**Main Role:** {self.main_role.name}\n"
                        f"**Target Roles:** {len(self.target_roles)} selected\n"
                        f"**Categories:** {len(self.selected_categories)} selected\n\n"
                        f"**Selected Categories:**\n" + "\n".join(category_info) + "\n\n"
                        f"**Total channels to create:** {len(self.target_roles) * len(self.selected_categories)}\n\n"
                        f"⚠️ **Ready to create organized 1-on-1 channels for competitions!**",
            color=discord.Color.green()
        )
        await interaction2.response.edit_message(embed=embed, view=self)

    async def create_channels_callback(self, interaction2: discord.Interaction):
        if interaction2.user != self.user:
            await interaction2.response.send_message("❌ Only the command user can create channels.", ephemeral=True)
            return
        await interaction2.response.defer(ephemeral=True)
        total_channels = len(self.target_roles) * len(self.selected_categories)
        created_count = 0
        failed_count = 0
        failed_channels = []
        created_channels = []
        progress_msg = await interaction2.followup.send(
            f"🚀 **Creating {total_channels} channels...**\n"
            f"Progress: 0/{total_channels} (0%)",
            ephemeral=True
        )
        sorted_target_roles = sorted(self.target_roles, key=lambda x: x.name.lower())
        for category in self.selected_categories:
            category_created = []
            for target_role in sorted_target_roles:
                try:
                    main_name = re.sub(r'[^a-zA-Z0-9]', '', self.main_role.name.lower())
                    target_name = re.sub(r'[^a-zA-Z0-9]', '', target_role.name.lower())
                    channel_name = f"{main_name}-{target_name}"
                    if len(channel_name) > 100:
                        channel_name = channel_name[:100]
                    overwrites = {
                        self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        self.main_role: discord.PermissionOverwrite(
                            view_channel=True, 
                            send_messages=True, 
                            read_messages=True,
                            read_message_history=True,
                            attach_files=True,
                            embed_links=True
                        ),
                        target_role: discord.PermissionOverwrite(
                            view_channel=True, 
                            send_messages=True, 
                            read_messages=True,
                            read_message_history=True,
                            attach_files=True,
                            embed_links=True
                        ),
                        self.guild.me: discord.PermissionOverwrite(
                            view_channel=True, 
                            send_messages=True, 
                            read_messages=True,
                            manage_messages=True
                        )
                    }
                    # Add mod role if option is enabled and mod_role_id is set and exists in guild
                    if self.add_mod_role and mod_role_id:
                        mod_role = self.guild.get_role(mod_role_id)
                        if mod_role:
                            overwrites[mod_role] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_messages=True,
                                read_message_history=True,
                                manage_messages=True
                            )
                    channel = await category.create_text_channel(
                        name=channel_name,
                        overwrites=overwrites,
                        reason=f"1-on-1 competition channel: {self.main_role.name} vs {target_role.name}",
                        topic=f"Private 1-on-1 channel between {self.main_role.name} and {target_role.name}"
                    )
                    created_count += 1
                    category_created.append(channel.name)
                    if created_count % 5 == 0 or created_count <= 3:
                        progress_percentage = int((created_count / total_channels) * 100)
                        try:
                            await progress_msg.edit(content=
                                f"🚀 **Creating {total_channels} channels...**\n"
                                f"Progress: {created_count}/{total_channels} ({progress_percentage}%)\n"
                                f"Current: {channel_name} in {category.name}"
                            )
                        except:
                            pass
                    await asyncio.sleep(0.1)
                except discord.Forbidden:
                    failed_count += 1
                    failed_channels.append(f"{main_name}-{target_name} in {category.name}: Missing permissions")
                except Exception as e:
                    failed_count += 1
                    failed_channels.append(f"{main_name}-{target_name} in {category.name}: {str(e)[:50]}")
            if category_created:
                created_channels.append(f"📂 **{category.name}**: {len(category_created)} channels")
        result_msg = f"✅ **1-on-1 Competition Channels Created!**\n\n"
        result_msg += f"**Success:** {created_count}/{total_channels} channels created\n"
        result_msg += f"**Main Role:** {self.main_role.name}\n"
        result_msg += f"**Target Roles:** {len(self.target_roles)} roles (sorted alphabetically)\n\n"
        if created_channels:
            result_msg += "**Created in:**\n" + "\n".join(created_channels) + "\n\n"
        if failed_count > 0:
            result_msg += f"**Failed:** {failed_count} channels\n\n"
            if len(failed_channels) <= 5:
                result_msg += "**Failed channels:**\n" + "\n".join(failed_channels)
            else:
                result_msg += f"**Failed channels:**\n" + "\n".join(failed_channels[:5])
                result_msg += f"\n... and {failed_count - 5} more"
        result_msg += "\n🎮 **All channels created with proper permissions for competition use!**"
        result_msg += "\n💡 **Tip:** Use `/sortcategory` if you need to reorder channels alphabetically."
        await interaction2.followup.send(result_msg, ephemeral=True)

# To add this cog to your bot:
# bot.add_cog(Generate1on1s(bot))

async def setup(bot):
    await bot.add_cog(Generate1on1s(bot))