import discord
from discord.ext import commands
from discord import app_commands
from bot.utils.helpers import is_mod, scoreboards, logger
import time

class ScoreboardCog(commands.Cog):
    """Scoreboard commands and views."""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="scoreboard", description="Create a scoreboard for points or elimination")
    async def scoreboard_cmd(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        class ScoreboardTypeView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                # ...existing code for ScoreboardTypeView...
                pass
            # ...add buttons if needed...

        await interaction.response.send_message(
            "📊 **Scoreboard Setup**\nSelect the type of game for the scoreboard:",
            view=ScoreboardTypeView(),
            ephemeral=True
        )

    class ScoreboardSetup(discord.ui.Modal):
        def __init__(self):
            super().__init__(title="Create Scoreboard")
            self.players = discord.ui.TextInput(
                label="Players or Teams (one per line)", 
                style=discord.TextStyle.paragraph,
                required=True
            )
            self.game_type = discord.ui.TextInput(
                label="Game Type (type 'points' or 'elimination')",
                style=discord.TextStyle.short,
                required=True,
                placeholder="points or elimination"
            )
            self.points_direction = discord.ui.TextInput(
                label="For points games: 'highest' or 'lowest' wins?",
                style=discord.TextStyle.short,
                required=False,
                placeholder="highest or lowest (only for points games)"
            )
            self.add_item(self.players)
            self.add_item(self.game_type)
            self.add_item(self.points_direction)

        async def on_submit(self, interaction: discord.Interaction):
            game_mode = self.game_type.value.lower().strip()
            if game_mode not in ['points', 'elimination']:
                await interaction.response.send_message("❌ Game type must be 'points' or 'elimination'.", ephemeral=True)
                return
            points_best = 'highest'
            if game_mode == 'points':
                if self.points_direction.value.strip():
                    points_best = self.points_direction.value.strip().lower()
            teams = [p.strip() for p in self.players.value.split('\n') if p.strip()]
            if not teams:
                await interaction.response.send_message("❌ Please provide at least one team/player.", ephemeral=True)
                return
            scoreboard = {
                'type': game_mode,
                'data': {team: 0 if game_mode == 'points' else 'Active' for team in teams},
                'control_channel': interaction.channel.id,
                'display_channel': None,
                'points_best': points_best if game_mode == 'points' else None,
                'display_message_id': None,
                'created_at': time.time()
            }
            scoreboards[interaction.channel.id] = scoreboard
            view = ScoreboardCog.ChannelSelectionView(scoreboard)
            await interaction.response.send_message("📍 Select where to post the public scoreboard:", view=view, ephemeral=True)

    class ChannelSelectionView(discord.ui.View):
        def __init__(self, scoreboard):
            super().__init__(timeout=300)
            self.scoreboard = scoreboard
            self.channel_select = discord.ui.ChannelSelect(
                placeholder="Select channel for public scoreboard display",
                channel_types=[discord.ChannelType.text],
                min_values=1, max_values=1
            )
            self.channel_select.callback = self.channel_callback
            self.add_item(self.channel_select)

        async def channel_callback(self, interaction: discord.Interaction):
            display_channel = interaction.guild.get_channel(int(interaction.data['values'][0]))
            self.scoreboard['display_channel'] = display_channel.id
            embed = ScoreboardCog.create_scoreboard_embed(self.scoreboard)
            display_message = await display_channel.send(embed=embed)
            self.scoreboard['display_message_id'] = display_message.id
            control_channel = interaction.guild.get_channel(self.scoreboard['control_channel'])
            control_embed = discord.Embed(
                title="🎮 Scoreboard Control Panel",
                description=f"**Display Channel:** {display_channel.mention}\n**Game Type:** {self.scoreboard['type'].title()}",
                color=discord.Color.green()
            )
            if self.scoreboard['type'] == 'points':
                control_embed.add_field(
                    name="Scoring", 
                    value=f"{self.scoreboard['points_best'].title()} points wins", 
                    inline=False
                )
            await control_channel.send(embed=control_embed, view=ScoreboardCog.ScoreboardButtons())
            await interaction.response.send_message(
                f"✅ Scoreboard created!\n"
                f"📺 **Display:** {display_channel.mention}\n"
                f"🎮 **Control:** {control_channel.mention}\n"
                f"Use the buttons in the control channel to manage the scoreboard.",
                ephemeral=True
            )

    class ScoreboardButtons(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="End Scoreboard", style=discord.ButtonStyle.success)
        async def end_scoreboard(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not is_mod(interaction):
                await interaction.response.send_message("❌ Only moderators can use this.", ephemeral=True)
                return
            sb = scoreboards.get(interaction.channel.id)
            if not sb:
                await interaction.response.send_message("❌ No active scoreboard found.", ephemeral=True)
                return
            scoreboards.pop(interaction.channel.id, None)
            await interaction.response.send_message("✅ Scoreboard ended!", ephemeral=True)

    @staticmethod
    def create_scoreboard_embed(scoreboard):
        embed = discord.Embed(
            title="📊 Scoreboard",
            color=discord.Color.blue()
        )
        if scoreboard['type'] == 'points':
            points = scoreboard['data']
            sorted_points = sorted(points.items(), key=lambda x: x[1], reverse=(scoreboard['points_best'] == 'highest'))
            desc = '\n'.join([f"**{team}**: {score}" for team, score in sorted_points])
            embed.description = desc
        else:
            teams = scoreboard['data']
            desc = '\n'.join([f"**{team}**: {status}" for team, status in teams.items()])
            embed.description = desc
        return embed

async def setup(bot):
    await bot.add_cog(ScoreboardCog(bot))
