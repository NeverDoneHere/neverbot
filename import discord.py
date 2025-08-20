import discord
from discord.ext import commands
from discord import app_commands
from bot.utils.helpers import logger, spin_wheel
import time
import re
import asyncio

class FunCog(commands.Cog):
    """Fun/game commands (spin, eversnow, reflex, etc.)"""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="spin", description="Spin a wheel with custom options!")
    @app_commands.describe(options="Comma-separated list of options to spin for")
    async def spin(self, interaction: discord.Interaction, options: str):
        await interaction.response.defer()
        try:
            option_list = [opt.strip() for opt in options.split(',') if opt.strip()]
            if len(option_list) < 2:
                await interaction.followup.send("❌ You need at least 2 options to spin!", ephemeral=True)
                return
            if len(option_list) > 20:
                await interaction.followup.send("❌ Maximum 20 options allowed!", ephemeral=True)
                return
            gif_bytes, winner = spin_wheel(option_list)
            file = discord.File(gif_bytes, filename="wheel_spin.gif")
            embed = discord.Embed(
                title="🎯 Wheel Spin Result",
                description=f"**Winner:** {winner}",
                color=discord.Color.gold()
            )
            embed.set_image(url="attachment://wheel_spin.gif")
            embed.set_footer(text=f"Spun by {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, file=file)
        except ValueError as e:
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error creating wheel: {str(e)}", ephemeral=True)
            logger.error(f"Wheel spin error: {e}")

    @app_commands.command(name="eversnow", description="Compare message timestamps using snowflake IDs to find the fastest.")
    @app_commands.describe(
        message1="First message ID or link",
        message2="Second message ID or link",
        message3="Third message ID or link (optional)",
        message4="Fourth message ID or link (optional)",
        message5="Fifth message ID or link (optional)"
    )
    async def eversnow(self, interaction: discord.Interaction, message1: str, message2: str, message3: str = None, message4: str = None, message5: str = None):
        await interaction.response.defer()
        try:
            message_inputs = [message1, message2]
            if message3: message_inputs.append(message3)
            if message4: message_inputs.append(message4)
            if message5: message_inputs.append(message5)
            message_data = []
            for i, msg_input in enumerate(message_inputs):
                try:
                    message_id = FunCog.extract_message_id(msg_input.strip())
                    if not message_id:
                        await interaction.followup.send(f"❌ Invalid message ID or link for message {i+1}: `{msg_input}`", ephemeral=True)
                        return
                    timestamp = FunCog.get_time_from_snowflake(int(message_id))
                    message_obj = None
                    channel_id = None
                    if "discord.com/channels/" in msg_input:
                        # TODO: Extract channel ID if needed
                        pass
                    message_data.append({
                        'id': message_id,
                        'timestamp': timestamp,
                        'input': msg_input,
                        'message_obj': message_obj,
                        'channel_id': channel_id,
                        'position': i + 1
                    })
                except ValueError:
                    await interaction.followup.send(f"❌ Invalid message ID format for message {i+1}: `{msg_input}`", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.followup.send(f"❌ Error processing message {i+1}: {str(e)}", ephemeral=True)
                    return
            sorted_messages = sorted(message_data, key=lambda x: x['timestamp'])
            fastest_message = sorted_messages[0]
            embed = discord.Embed(
                title="⏱️ EverSnow - Message Timestamp Comparison",
                description="Comparing message timestamps using Discord snowflake IDs",
                color=discord.Color.blue()
            )
            results_text = ""
            for i, msg in enumerate(sorted_messages):
                is_fastest = msg['id'] == fastest_message['id']
                emoji = "✅" if is_fastest else "📝"
                timestamp_str = str(msg['timestamp'])
                results_text += f"{emoji} **Message {msg['position']}**\n"
                results_text += f"└ Time: `{timestamp_str}`\n"
                results_text += f"└ ID: `{msg['id']}`\n"
                if msg['message_obj']:
                    content = msg['message_obj'].content
                    if content:
                        preview = content[:50] + "..." if len(content) > 50 else content
                        results_text += f"└ Preview: {preview}\n"
                    results_text += f"└ Author: {msg['message_obj'].author.mention}\n"
                results_text += "\n"
            embed.add_field(
                name="📊 Results (Sorted by Speed)",
                value=results_text,
                inline=False
            )
            time_diff_ms = (sorted_messages[-1]['timestamp'] - fastest_message['timestamp']).total_seconds() * 1000 if len(sorted_messages) > 1 else 0
            details_text = f"**Fastest Message:** Message {fastest_message['position']} ✅\n"
            details_text += f"**Time Difference:** {time_diff_ms:.1f}ms between first and last\n"
            details_text += f"**Total Messages:** {len(message_data)}"
            embed.add_field(
                name="⚡ Speed Analysis",
                value=details_text,
                inline=False
            )
            embed.set_footer(
                text=f"Requested by {interaction.user.display_name} • Use message IDs or links",
                icon_url=interaction.user.display_avatar.url
            )
            view = FunCog.EverSnowView(message_data, fastest_message)
            await interaction.followup.send(embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"❌ Error comparing messages: {str(e)}", ephemeral=True)
            logger.error(f"EverSnow error: {e}")

    @staticmethod
    def extract_message_id(input_str: str) -> str:
        input_str = input_str.strip()
        if "discord.com/channels/" in input_str:
            parts = input_str.split("/")
            if len(parts) >= 1:
                return parts[-1]
        elif input_str.isdigit() and len(input_str) >= 17:
            return input_str
        numbers = re.findall(r'\d+', input_str)
        for num in numbers:
            if len(num) >= 17:
                return num
        return None

    @staticmethod
    def get_time_from_snowflake(snowflake: int):
        # TODO: Implement actual snowflake to datetime conversion
        return snowflake

    class EverSnowView(discord.ui.View):
        def __init__(self, message_data, fastest_message):
            super().__init__(timeout=300)
            self.message_data = message_data
            self.fastest_message = fastest_message
        @discord.ui.button(label="🎯 React to Fastest", style=discord.ButtonStyle.success)
        async def react_to_fastest(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message("Stub: Reacted to fastest.", ephemeral=True)
        @discord.ui.button(label="📋 Copy Fastest ID", style=discord.ButtonStyle.secondary)
        async def copy_fastest_id(self, interaction: discord.Interaction, button: discord.ui.Button):
            fastest_id = self.fastest_message['id']
            await interaction.response.send_message(
                f"📋 **Fastest Message ID:** `{fastest_id}`\n💡 **Tip:** You can copy this ID for future reference!",
                ephemeral=True
            )
        @discord.ui.button(label="🔗 Show Links", style=discord.ButtonStyle.primary)
        async def show_links(self, interaction: discord.Interaction, button: discord.ui.Button):
            links_text = "🔗 **Message Links:**\n\n"
            for msg in self.message_data:
                emoji = "✅" if msg['id'] == self.fastest_message['id'] else "📝"
                if msg['channel_id'] and interaction.guild:
                    link = f"https://discord.com/channels/{interaction.guild.id}/{msg['channel_id']}/{msg['id']}"
                    links_text += f"{emoji} **Message {msg['position']}:** [Jump to Message]({link})\n"
                else:
                    links_text += f"{emoji} **Message {msg['position']}:** `{msg['id']}` (no link available)\n"
            embed = discord.Embed(
                title="🔗 Message Links",
                description=links_text,
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="redlightgreenlight", description="Start a Red Light Green Light reflex game.")
    async def redlightgreenlight(self, interaction: discord.Interaction):
        # TODO: Move your redlightgreenlight logic here
        pass

    class ReflexGameSetupModal(discord.ui.Modal):
        def __init__(self):
            super().__init__(title="Red Light Green Light Setup")
            # ...existing code...
            pass

    class RoleSelectionView(discord.ui.View):
        def __init__(self, round_time, max_elims, eliminate_slowest):
            super().__init__(timeout=300)
            # ...existing code...
            pass

    class ReflexGame(discord.ui.View):
        def __init__(self, moderator, eligible_roles, round_time, max_elims, eliminate_slowest):
            super().__init__(timeout=None)
            # ...existing code...
            pass

    @app_commands.command(name="vc_snapshot", description="Take a snapshot of a voice channel now or set a timer to post results later.")
    @app_commands.describe(
        channel="The voice channel to snapshot",
        mode="Choose 'now' for immediate snapshot or 'timer' to schedule one"
    )
    async def vc_snapshot(self, interaction: discord.Interaction, channel: discord.VoiceChannel, mode: str):
        """
        /vc_snapshot <channel> <mode>
        mode: 'now' or 'timer'
        """
        if mode.lower() == 'now':
            await self.send_vc_snapshot(interaction, channel)
        elif mode.lower() == 'timer':
            # Show modal to get timer duration
            await interaction.response.send_modal(self.VCSnapshotTimerModal(self, channel))
        else:
            await interaction.response.send_message("❌ Invalid mode. Use 'now' or 'timer'!", ephemeral=True)

    async def send_vc_snapshot(self, interaction, channel):
        members = [m for m in channel.members if not m.bot]
        embed = discord.Embed(
            title=f"🔊 VC Snapshot: {channel.name}",
            description=f"**Total Members:** {len(members)}",
            color=discord.Color.blue()
        )
        if members:
            member_list = '\n'.join([f"{m.display_name} ({m.id})" for m in members])
            embed.add_field(name="Members", value=member_list, inline=False)
        else:
            embed.add_field(name="Members", value="No users in channel.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    class VCSnapshotTimerModal(discord.ui.Modal, title="Set VC Snapshot Timer"):
        def __init__(self, cog, channel):
            super().__init__()
            self.cog = cog
            self.channel = channel
            self.duration = discord.ui.TextInput(
                label="Timer Duration (seconds, e.g. 60)",
                style=discord.TextStyle.short,
                required=True,
                placeholder="60"
            )
            self.add_item(self.duration)
        async def on_submit(self, interaction: discord.Interaction):
            try:
                seconds = int(self.duration.value.strip())
                if seconds < 5 or seconds > 86400:
                    await interaction.response.send_message("❌ Duration must be between 5 and 86400 seconds (24h).", ephemeral=True)
                    return
                await interaction.response.send_message(f"⏳ Snapshot scheduled in {seconds} seconds! Results will be posted here.", ephemeral=True)
                await asyncio.sleep(seconds)
                await self.cog.send_vc_snapshot(interaction, self.channel)
            except Exception as e:
                await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(FunCog(bot))