import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random

class RedLightGreenLight(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}  # guild_id: GameState

    class GameState:
        def __init__(self, host, channel):
            self.host = host
            self.channel = channel
            self.players = {}  # user_id: {"member": member, "lives": int, "eliminated": bool}
            self.allowed_roles = []
            self.max_eliminated = 1
            self.lives_enabled = False
            self.lives_count = 1
            self.eliminate_slowest = False
            self.in_progress = False
            self.round = 0
            self.eliminated_count = 0
            self.join_message = None
            self.mod_view_message = None
            self.round_task = None
            self.control_mode = "random"  # or "manual"
            self.mod_control_user = None

    # --- Setup command ---
    @app_commands.command(name="redlightgreenlight", description="Start a Red Light Green Light game setup.")
    async def redlightgreenlight(self, interaction: discord.Interaction):
        # Only allow one game per channel
        if interaction.guild_id in self.active_games:
            await interaction.response.send_message("A game is already running in this server.", ephemeral=True)
            return

        # Setup menu view
        view = self.SetupView(self, interaction)
        await interaction.response.send_message("🎮 **Red Light Green Light Setup**", view=view, ephemeral=True)

    class SetupView(discord.ui.View):
        def __init__(self, cog, interaction):
            super().__init__(timeout=600)
            self.cog = cog
            self.interaction = interaction
            self.allowed_roles = []
            self.lives_enabled = False
            self.lives_count = 1
            self.eliminate_slowest = False
            self.max_eliminated = 1
            self.control_mode = "random"
            self.setup_complete = False

            # Add role select
            self.add_item(self.RoleSelect(self))
            # Add toggle lives
            self.add_item(self.LivesToggle(self))
            # Add eliminate slowest toggle
            self.add_item(self.EliminateSlowestToggle(self))
            # Add max eliminated input
            self.add_item(self.MaxEliminatedInput(self))
            # Add control mode select
            self.add_item(self.ControlModeSelect(self))
            # Add start/cancel buttons
            self.add_item(self.StartButton(self))
            self.add_item(self.CancelButton(self))

        class RoleSelect(discord.ui.Select):
            def __init__(self, parent):
                options = [
                    discord.SelectOption(label=role.name, value=str(role.id))
                    for role in parent.interaction.guild.roles if not role.is_bot_managed()
                ][:25]
                super().__init__(placeholder="Select roles who can play...", options=options, min_values=1, max_values=len(options))
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                self.parent.allowed_roles = [int(v) for v in self.values]
                await interaction.response.send_message("Roles updated.", ephemeral=True)

        class LivesToggle(discord.ui.Select):
            def __init__(self, parent):
                options = [
                    discord.SelectOption(label="Immediate Elimination", value="off"),
                    discord.SelectOption(label="Enable Lives", value="on"),
                ]
                super().__init__(placeholder="Lives or Elimination?", options=options, min_values=1, max_values=1)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                self.parent.lives_enabled = (self.values[0] == "on")
                if self.parent.lives_enabled:
                    # Ask for lives count
                    await interaction.response.send_modal(self.parent.LivesCountModal(self.parent))
                else:
                    await interaction.response.send_message("Players will be eliminated immediately.", ephemeral=True)

        class LivesCountModal(discord.ui.Modal, title="Set Number of Lives"):
            def __init__(self, parent):
                super().__init__()
                self.parent = parent
                self.lives_input = discord.ui.TextInput(label="Lives per player", required=True, max_length=2, placeholder="e.g. 3")
                self.add_item(self.lives_input)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    count = int(self.lives_input.value)
                    self.parent.lives_count = max(1, count)
                    await interaction.response.send_message(f"Lives set to {self.parent.lives_count}.", ephemeral=True)
                except:
                    await interaction.response.send_message("Invalid number.", ephemeral=True)

        class EliminateSlowestToggle(discord.ui.Select):
            def __init__(self, parent):
                options = [
                    discord.SelectOption(label="Eliminate slowest player each round", value="on"),
                    discord.SelectOption(label="No slowest elimination", value="off"),
                ]
                super().__init__(placeholder="Eliminate slowest?", options=options, min_values=1, max_values=1)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                self.parent.eliminate_slowest = (self.values[0] == "on")
                await interaction.response.send_message(
                    "Slowest elimination enabled." if self.parent.eliminate_slowest else "Slowest elimination disabled.",
                    ephemeral=True
                )

        class MaxEliminatedInput(discord.ui.Button):
            def __init__(self, parent):
                super().__init__(label="Set Max Eliminated", style=discord.ButtonStyle.primary)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_modal(self.parent.MaxEliminatedModal(self.parent))

        class MaxEliminatedModal(discord.ui.Modal, title="Set Max Eliminated"):
            def __init__(self, parent):
                super().__init__()
                self.parent = parent
                self.max_input = discord.ui.TextInput(label="Max players eliminated before game ends", required=True, max_length=2, placeholder="e.g. 5")
                self.add_item(self.max_input)

            async def on_submit(self, interaction: discord.Interaction):
                try:
                    count = int(self.max_input.value)
                    self.parent.max_eliminated = max(1, count)
                    await interaction.response.send_message(f"Max eliminated set to {self.parent.max_eliminated}.", ephemeral=True)
                except:
                    await interaction.response.send_message("Invalid number.", ephemeral=True)

        class ControlModeSelect(discord.ui.Select):
            def __init__(self, parent):
                options = [
                    discord.SelectOption(label="Randomized Rounds", value="random"),
                    discord.SelectOption(label="Manual Mod Control", value="manual"),
                ]
                super().__init__(placeholder="Round control mode...", options=options, min_values=1, max_values=1)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                self.parent.control_mode = self.values[0]
                await interaction.response.send_message(
                    "Manual mod control enabled." if self.parent.control_mode == "manual" else "Randomized rounds enabled.",
                    ephemeral=True
                )

        class StartButton(discord.ui.Button):
            def __init__(self, parent):
                super().__init__(label="Start Game", style=discord.ButtonStyle.success)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                # Save config and move to join screen
                if not self.parent.allowed_roles:
                    await interaction.response.send_message("Please select at least one role.", ephemeral=True)
                    return
                await self.parent.cog.start_join_screen(interaction, self.parent)

        class CancelButton(discord.ui.Button):
            def __init__(self, parent):
                super().__init__(label="Cancel", style=discord.ButtonStyle.danger)
                self.parent = parent

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_message("Game setup cancelled.", ephemeral=True)
                self.parent.stop()

    async def start_join_screen(self, interaction, setup_view):
        # Create game state
        state = self.GameState(host=interaction.user, channel=interaction.channel)
        state.allowed_roles = setup_view.allowed_roles
        state.lives_enabled = setup_view.lives_enabled
        state.lives_count = setup_view.lives_count
        state.eliminate_slowest = setup_view.eliminate_slowest
        state.max_eliminated = setup_view.max_eliminated
        state.control_mode = setup_view.control_mode
        self.active_games[interaction.guild_id] = state

        # Join screen view
        join_view = self.JoinView(self, state)
        msg = await interaction.channel.send(
            "🟢 **Red Light Green Light**\nClick **Join** to play! (Only allowed roles can join)\nMods can Start or Cancel.",
            view=join_view
        )
        state.join_message = msg

    class JoinView(discord.ui.View):
        def __init__(self, cog, state):
            super().__init__(timeout=600)
            self.cog = cog
            self.state = state

        @discord.ui.button(label="Join", style=discord.ButtonStyle.primary)
        async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Only allowed roles
            if not any(role.id in self.state.allowed_roles for role in interaction.user.roles):
                await interaction.response.send_message("You are not allowed to join.", ephemeral=True)
                return
            if interaction.user.id in self.state.players:
                await interaction.response.send_message("You already joined.", ephemeral=True)
                return
            self.state.players[interaction.user.id] = {
                "member": interaction.user,
                "lives": self.state.lives_count if self.state.lives_enabled else 1,
                "eliminated": False
            }
            await interaction.response.send_message("You joined the game!", ephemeral=True)

        @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
        async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Only host or mod
            if interaction.user != self.state.host and not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("Only the host or a mod can start.", ephemeral=True)
                return
            if len(self.state.players) < 2:
                await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
                return
            self.state.in_progress = True
            await interaction.response.send_message("Game starting!", ephemeral=True)
            await self.cog.run_game(self.state)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Only host or mod
            if interaction.user != self.state.host and not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("Only the host or a mod can cancel.", ephemeral=True)
                return
            await interaction.response.send_message("Game cancelled.", ephemeral=True)
            self.cog.active_games.pop(interaction.guild_id, None)
            self.stop()

    async def run_game(self, state):
        channel = state.channel
        players = state.players
        eliminated = set()
        round_num = 0

        while True:
            round_num += 1

            # --- Decide round type ---
            if state.control_mode == "manual":
                # Show mod control panel to select round type
                mod_panel = self.ModRoundControlView(self, state)
                # Only host and mods see this
                mod_msg = await channel.send(
                    f"🔒 **Mod Control Panel**\nSelect the next round type below.",
                    view=mod_panel,
                    silent=True  # Only mods/host should see, or DM if you want
                )
                state.mod_view_message = mod_msg
                # Wait for mod to pick round type
                try:
                    round_type = await mod_panel.wait_for_choice()
                except asyncio.TimeoutError:
                    await channel.send("⏰ Mod did not select a round type in time. Ending game.")
                    self.active_games.pop(channel.guild.id, None)
                    break
                await mod_msg.delete()
            else:
                # Randomized round
                is_green = random.choice([True, False, False])  # More reds than greens
                trick = random.random() < 0.15  # 15% chance of trick round
                round_type = "trick" if trick else ("green" if is_green else "red")

            # Announce round
            desc = {
                "green": "🟢 **GREEN LIGHT!** Press the button to move!",
                "red": "🔴 **RED LIGHT!** Do NOT press the button!",
                "trick": "🟡 **TRICK ROUND!** (Will it be green or red? 🤔)"
            }[round_type]
            view = self.RoundView(self, state, round_type)
            msg = await channel.send(f"**Round {round_num}**\n{desc}", view=view)

            # Wait for responses
            await asyncio.sleep(8)
            await msg.edit(view=None)

            # Evaluate moves
            moves = view.moves  # user_id: True if moved
            round_eliminated = []

            for uid, pdata in players.items():
                if pdata["eliminated"]:
                    continue
                moved = moves.get(uid, False)
                if round_type == "green":
                    if not moved:
                        round_eliminated.append(uid)
                elif round_type == "red":
                    if moved:
                        round_eliminated.append(uid)
                elif round_type == "trick":
                    # Trick: randomly decide if it's green or red for this round
                    trick_is_green = random.choice([True, False])
                    if trick_is_green:
                        if not moved:
                            round_eliminated.append(uid)
                    else:
                        if moved:
                            round_eliminated.append(uid)

            # Eliminate slowest if enabled
            if state.eliminate_slowest and round_type == "green":
                if moves:
                    slowest = max(moves.items(), key=lambda x: x[1])[0]
                    if slowest not in round_eliminated:
                        round_eliminated.append(slowest)

            # Handle lives/elimination
            for uid in round_eliminated:
                pdata = players[uid]
                if state.lives_enabled:
                    pdata["lives"] -= 1
                    if pdata["lives"] <= 0:
                        pdata["eliminated"] = True
                        eliminated.add(uid)
                else:
                    pdata["eliminated"] = True
                    eliminated.add(uid)

            # Announce eliminated
            if round_eliminated:
                elim_names = [players[uid]["member"].mention for uid in round_eliminated]
                await channel.send(f"💀 Eliminated this round: {', '.join(elim_names)}")
            else:
                await channel.send("✅ No one eliminated this round!")

            # Check end conditions
            if len(eliminated) >= state.max_eliminated or sum(not p["eliminated"] for p in players.values()) <= 1:
                winners = [p["member"].mention for p in players.values() if not p["eliminated"]]
                await channel.send(f"🏁 **Game Over!**\nWinners: {', '.join(winners) if winners else 'None'}")
                self.active_games.pop(channel.guild.id, None)
                break

    class RoundView(discord.ui.View):
        def __init__(self, cog, state, round_type):
            super().__init__(timeout=8)
            self.cog = cog
            self.state = state
            self.round_type = round_type
            self.moves = {}  # user_id: True if moved

        @discord.ui.button(label="Move!", style=discord.ButtonStyle.success)
        async def move(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in self.state.players or self.state.players[interaction.user.id]["eliminated"]:
                await interaction.response.send_message("You are not in the game or already eliminated.", ephemeral=True)
                return
            self.moves[interaction.user.id] = True
            await interaction.response.send_message("You moved!", ephemeral=True)

    class ModRoundControlView(discord.ui.View):
        def __init__(self, cog, state):
            super().__init__(timeout=30)
            self.cog = cog
            self.state = state
            self.choice = None
            self._waiter = asyncio.get_event_loop().create_future()

        @discord.ui.button(label="Green Light", style=discord.ButtonStyle.success)
        async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self._is_mod(interaction):
                await interaction.response.send_message("Only the host or a mod can control rounds.", ephemeral=True)
                return
            self.choice = "green"
            await interaction.response.send_message("Next round: Green Light", ephemeral=True)
            self._waiter.set_result(self.choice)
            self.disable_all_items()
            await interaction.message.edit(view=self)

        @discord.ui.button(label="Red Light", style=discord.ButtonStyle.danger)
        async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self._is_mod(interaction):
                await interaction.response.send_message("Only the host or a mod can control rounds.", ephemeral=True)
                return
            self.choice = "red"
            await interaction.response.send_message("Next round: Red Light", ephemeral=True)
            self._waiter.set_result(self.choice)
            self.disable_all_items()
            await interaction.message.edit(view=self)

        @discord.ui.button(label="Trick Round", style=discord.ButtonStyle.primary)
        async def trick(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self._is_mod(interaction):
                await interaction.response.send_message("Only the host or a mod can control rounds.", ephemeral=True)
                return
            self.choice = "trick"
            await interaction.response.send_message("Next round: Trick Round", ephemeral=True)
            self._waiter.set_result(self.choice)
            self.disable_all_items()
            await interaction.message.edit(view=self)

        def _is_mod(self, interaction):
            return interaction.user == self.state.host or interaction.user.guild_permissions.manage_guild

        async def wait_for_choice(self):
            return await asyncio.wait_for(self._waiter, timeout=30)

    # --- End/Cancel command for mods ---
    @app_commands.command(name="endredlightgreenlight", description="End or cancel the current Red Light Green Light game.")
    async def endredlightgreenlight(self, interaction: discord.Interaction):
        state = self.active_games.get(interaction.guild_id)
        if not state:
            await interaction.response.send_message("No game is running.", ephemeral=True)
            return
        if interaction.user != state.host and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Only the host or a mod can end the game.", ephemeral=True)
            return
        self.active_games.pop(interaction.guild_id, None)
        await interaction.response.send_message("Game ended.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RedLightGreenLight(bot))
