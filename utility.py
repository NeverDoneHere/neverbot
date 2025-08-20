import discord
from discord.ext import commands
from discord import app_commands
from bot.utils.helpers import logger

class UtilityCog(commands.Cog):
    """Utility commands and error handlers."""
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.MissingPermissions):
                await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            elif isinstance(error, app_commands.CommandOnCooldown):
                await interaction.response.send_message(f"⏳ This command is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)
            elif isinstance(error, app_commands.BotMissingPermissions):
                await interaction.response.send_message("❌ I'm missing permissions to execute this command.", ephemeral=True)
            else:
                logger.error(f"Command error in {getattr(interaction, 'command', None)}: {error}", exc_info=True)
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message("❌ An unexpected error occurred. Please try again.", ephemeral=True)
                    else:
                        await interaction.followup.send("❌ An unexpected error occurred. Please try again.", ephemeral=True)
                except:
                    pass
        except Exception as e:
            logger.error(f"Error in command error handler: {e}")

async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
    async def eliminated_namechange(self, interaction: discord.Interaction):
        from bot.utils.helpers import is_mod
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command. (is_mod failed)", ephemeral=True)
            return

        class EliminateNameView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.selected_users = []
                self.selected_role = None
                self.user_selector = discord.ui.UserSelect(
                    placeholder="Search and select users to eliminate (with name change)", min_values=1, max_values=25
                )
                self.role_selector = discord.ui.RoleSelect(
                    placeholder="Select a role to assign after elimination", min_values=1, max_values=1
                )
                self.user_selector.callback = self.user_callback
                self.role_selector.callback = self.role_callback
                self.add_item(self.user_selector)
                self.add_item(self.role_selector)

            async def user_callback(self, interaction2: discord.Interaction):
                self.selected_users = self.user_selector.values
                await interaction2.response.defer()

            async def role_callback(self, interaction2: discord.Interaction):
                self.selected_role = self.role_selector.values[0] if self.role_selector.values else None
                await interaction2.response.defer()

            @discord.ui.button(label="Eliminate (With Name Change)", style=discord.ButtonStyle.danger)
            async def eliminate_button(self, interaction2: discord.Interaction, button: discord.ui.Button):
                if not self.selected_users or not self.selected_role:
                    await interaction2.response.send_message("❌ Please select users and a role.", ephemeral=True)
                    return
                count = 0
                failed = []
                for user in self.selected_users:
                    member = interaction.guild.get_member(user.id)
                    if member:
                        try:
                            roles_to_remove = [role for role in member.roles if role != interaction.guild.default_role]
                            if roles_to_remove:
                                try:
                                    await member.remove_roles(*roles_to_remove, reason="Eliminated (with name change)")
                                except discord.Forbidden:
                                    failed.append(f"{member.display_name} (missing Manage Roles permission)")
                                    continue
                            new_nick = "💀 ELIMINATED"
                            if len(new_nick) > 32:
                                new_nick = new_nick[:32]
                            try:
                                await member.edit(nick=new_nick)
                            except discord.Forbidden:
                                failed.append(f"{member.display_name} (missing Manage Nicknames permission)")
                                continue
                            try:
                                await member.add_roles(self.selected_role, reason="Eliminated (with name change)")
                            except discord.Forbidden:
                                failed.append(f"{member.display_name} (cannot add role: check bot's role position)")
                                continue
                            count += 1
                        except Exception as e:
                            failed.append(f"{member.display_name} ({e})")
                msg = f"✅ Eliminated (with name change) {count} member(s)."
                if failed:
                    msg += f"\n⚠️ Failed for: {', '.join(failed)}"
                await interaction2.response.send_message(msg, ephemeral=True)

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel_button(self, interaction2: discord.Interaction, button: discord.ui.Button):
                await interaction2.response.send_message("❌ Action cancelled.", ephemeral=True)

        await interaction.response.send_message(
            "👥 Search and select users to eliminate (with name change), then choose a role to assign:", ephemeral=True, view=EliminateNameView()
        )

async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
