import discord
from discord.ext import commands
from discord import app_commands

class VCTrapdoorLock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.vc_config = {}  # {channel_id: role_id}
        self.vc_locked_members = {}  # {channel_id: [member_ids]}

    # Setup command for mods to register lockable VCs
    @app_commands.command(name="vc_lock_setup", description="Set up a VC and lock role")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def vc_lock_setup(self, interaction: discord.Interaction,
                            channel: discord.VoiceChannel,
                            role: discord.Role):
        self.vc_config[channel.id] = role.id
        await interaction.response.send_message(
            f"✅ {channel.name} is now lockable by role {role.name}.", ephemeral=True
        )

    # Command to lock a VC
    @app_commands.command(name="lock_vc", description="Lock a voice channel so no one else can join")
    async def lock_vc(self, interaction: discord.Interaction,
                      channel: discord.VoiceChannel = None):
        user = interaction.user
        channel = channel or getattr(user.voice, 'channel', None)

        if not channel:
            return await interaction.response.send_message("You're not in a VC and no channel was selected.", ephemeral=True)

        role_id = self.vc_config.get(channel.id)
        if not role_id:
            return await interaction.response.send_message("This VC is not configured for locking.", ephemeral=True)

        lock_role = interaction.guild.get_role(role_id)
        if lock_role not in user.roles:
            return await interaction.response.send_message("You don’t have permission to lock this VC.", ephemeral=True)

        # Lock the VC for everyone
        self.vc_locked_members[channel.id] = [m.id for m in channel.members]

        for role in channel.guild.roles:
            overwrite = channel.overwrites_for(role)
            overwrite.connect = False
            await channel.set_permissions(role, overwrite=overwrite)

        await interaction.response.send_message(f"🔒 `{channel.name}` is now locked.")

    # Listener to auto-unlock when someone leaves
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and before.channel.id in self.vc_locked_members:
            prev_members = self.vc_locked_members[before.channel.id]
            if member.id in prev_members:
                # Someone from the locked group left
                await self.unlock_vc(before.channel)

    # Unlock helper
    async def unlock_vc(self, channel):
        for role in channel.guild.roles:
            overwrite = channel.overwrites_for(role)
            overwrite.connect = True
            await channel.set_permissions(role, overwrite=overwrite)

        self.vc_locked_members.pop(channel.id, None)

        # Optional: Notify a log channel or system channel
        if channel.guild.system_channel:
            await channel.guild.system_channel.send(f"🔓 `{channel.name}` is now unlocked.")

# Register Cog
async def setup(bot):
    await bot.add_cog(VCTrapdoorLock(bot))
