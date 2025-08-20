import discord
from discord.ext import commands
from discord import app_commands
from ..utils.helpers import is_mod, active_votes, logger
import time
import re
import asyncio




class VoteCog(commands.Cog):
    """Voting commands and views."""
    def __init__(self, bot):
        self.bot = bot
        self.vote_counter = 0  # For unique vote IDs

    @app_commands.command(name="startvote", description="Start an anonymous vote with interactive setup.")
    async def startvote(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        # Increment vote counter for unique vote_id
        self.vote_counter += 1
        vote_id = int(time.time() * 1000)  # Use timestamp for uniqueness
        await interaction.response.send_modal(VoteCog.VoteSetupModal(self.bot, vote_id))

    class VoteSetupModal(discord.ui.Modal, title="Vote Setup"):
        def __init__(self, bot, vote_id):
            super().__init__()
            self.bot = bot
            self.vote_id = vote_id
            self.title_input = discord.ui.TextInput(
                label="Vote Title", max_length=100, required=True, placeholder="e.g. Team Captain Election"
            )
            self.question_input = discord.ui.TextInput(
                label="Vote Question", style=discord.TextStyle.paragraph, max_length=200, required=True
            )
            self.options_input = discord.ui.TextInput(
                label="Options (comma-separated)", max_length=500, required=True, placeholder="Option 1, Option 2, Option 3..."
            )
            self.duration_input = discord.ui.TextInput(
                label="Vote Duration (minutes, optional)",
                max_length=5,
                required=False,
                placeholder="Leave blank for no timer"
            )
            self.add_item(self.title_input)
            self.add_item(self.question_input)
            self.add_item(self.options_input)
            self.add_item(self.duration_input)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.send_message(
                "Select vote channel, results channel, eligible roles, and vote change option below.",
                ephemeral=True,
                view=VoteCog.VoteSetupView(
                    self.title_input.value,
                    self.question_input.value,
                    self.options_input.value,
                    self.duration_input.value,
                    self.bot,
                    self.vote_id
                )
            )

    class VoteSetupView(discord.ui.View):
        def __init__(self, vote_title, vote_question, options_raw, duration_raw, bot, vote_id):
            super().__init__(timeout=300)
            self.bot = bot
            self.vote_title = vote_title
            self.vote_question = vote_question
            self.options_raw = options_raw
            self.duration_raw = duration_raw
            self.vote_id = vote_id
            self.vote_channel = None
            self.results_channel = None
            self.create_new_results_channel = False
            self.allow_changes = False
            self.eligible_roles = []
            self.results_permissions_roles = []
            # Channel select
            self.channel_select = discord.ui.ChannelSelect(
                placeholder="Select channel to post vote",
                channel_types=[discord.ChannelType.text],
                min_values=1, max_values=1
            )
            self.channel_select.callback = self.channel_callback
            self.add_item(self.channel_select)
            # Results channel select
            self.results_channel_select = discord.ui.ChannelSelect(
                placeholder="Select results channel (or leave blank to create new)",
                channel_types=[discord.ChannelType.text],
                min_values=0, max_values=1
            )
            self.results_channel_select.callback = self.results_channel_callback
            self.add_item(self.results_channel_select)
            # Eligible roles
            self.role_select = discord.ui.RoleSelect(
                placeholder="Select roles that can vote",
                min_values=1, max_values=5
            )
            self.role_select.callback = self.role_callback
            self.add_item(self.role_select)
            # Allow vote changes
            self.allow_changes_select = discord.ui.Select(
                placeholder="Allow vote changes?",
                options=[
                    discord.SelectOption(label="Allow vote changes", value="true"),
                    discord.SelectOption(label="Do NOT allow vote changes", value="false")
                ],
                min_values=1, max_values=1
            )
            self.allow_changes_select.callback = self.allow_changes_callback
            self.add_item(self.allow_changes_select)
            # Create vote button
            self.create_vote_button = discord.ui.Button(label="Create Vote", style=discord.ButtonStyle.green)
            self.create_vote_button.callback = self.create_vote
            self.add_item(self.create_vote_button)

        async def channel_callback(self, interaction: discord.Interaction):
            self.vote_channel = self.channel_select.values[0]
            await interaction.response.defer()

        async def results_channel_callback(self, interaction: discord.Interaction):
            if self.results_channel_select.values:
                self.results_channel = self.results_channel_select.values[0]
                self.create_new_results_channel = False
            else:
                self.results_channel = None
                self.create_new_results_channel = True
            await interaction.response.defer()

        async def role_callback(self, interaction: discord.Interaction):
            self.eligible_roles = self.role_select.values
            await interaction.response.defer()

        async def allow_changes_callback(self, interaction: discord.Interaction):
            self.allow_changes = self.allow_changes_select.values[0] == "true"
            await interaction.response.defer()

        async def create_vote(self, interaction: discord.Interaction):
            # Validate and create vote
            options_list = [opt.strip() for opt in self.options_raw.split(',') if opt.strip()]
            if len(options_list) < 2:
                await interaction.response.send_message("❌ At least 2 options required.", ephemeral=True)
                return
            guild = interaction.guild
            # Fix: get the actual TextChannel object from the ID
            vote_channel = guild.get_channel(self.vote_channel.id) if hasattr(self.vote_channel, "id") else self.vote_channel
            eligible_roles = [
                r if hasattr(r, "members") else guild.get_role(int(r))
                for r in self.eligible_roles
            ]
            # Results channel logic
            results_channel = None
            if self.create_new_results_channel:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True)
                }
                # Only mods can see results
                for role in guild.roles:
                    if is_mod(role):
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True)
                results_channel = await guild.create_text_channel("vote-results", overwrites=overwrites)
            else:
                if self.results_channel:
                    results_channel = guild.get_channel(self.results_channel.id) if hasattr(self.results_channel, "id") else self.results_channel
            # Duration handling
            duration_minutes = None
            timer_text = ""
            close_time_text = ""
            try:
                if self.duration_raw and self.duration_raw.strip():
                    duration_minutes = int(self.duration_raw.strip())
                    if duration_minutes < 1 or duration_minutes > 1440:
                        await interaction.response.send_message("❌ Duration must be between 1 and 1440 minutes.", ephemeral=True)
                        return
                    # Calculate close time
                    close_time = (discord.utils.utcnow() + discord.utils.timedelta(minutes=duration_minutes)).strftime("%I:%M %p").lstrip("0")
                    timer_text = f"\n\n⏰ **Voting closes in {duration_minutes} minute(s) ({close_time} server time).**"
                    close_time_text = f"Closes at {close_time} server time"
            except Exception:
                await interaction.response.send_message("❌ Invalid duration value.", ephemeral=True)
                return
            # Store vote data
            vote_data = {
                "title": self.vote_title,
                "question": self.vote_question,
                "options": options_list,
                "votes": {},
                "eligible_role_ids": [r.id for r in eligible_roles if r],
                "results_channel_id": results_channel.id if results_channel else None,
                "allow_changes": self.allow_changes,
                "created_at": time.time(),
                "duration_minutes": duration_minutes,
                "vote_channel_id": vote_channel.id,
                "results_message_id": None,  # Will be set after sending
                "vote_message_id": None      # Will be set after sending
            }
            # Post vote
            number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            divider = "\n" + "―" * 20 + "\n"
            options_text = divider.join(
                f"{number_emojis[i]} **{opt}**" if i < len(number_emojis) else f"{i+1}. **{opt}**"
                for i, opt in enumerate(options_list)
            )
            embed = discord.Embed(
                title=f"🗳️ {self.vote_title}",
                description=f"**{self.vote_question}**\n\n**How to Vote:**\nClick a button below to cast your vote anonymously.{timer_text}",
                color=discord.Color.blurple()
            )
            embed.add_field(name="__**Options**__", value=options_text, inline=False)
            eligible_names = ", ".join([r.name for r in eligible_roles if r])
            embed.add_field(name="Eligible Voters", value=eligible_names, inline=True)
            embed.add_field(name="Vote Changes", value="✅ Allowed" if self.allow_changes else "❌ Not Allowed", inline=True)
            if close_time_text:
                embed.set_footer(text=close_time_text)
            view = VoteCog.VoteButtonsView(options_list, eligible_roles, interaction.guild.id, self.vote_id)
            vote_msg = await vote_channel.send(embed=embed, view=view)
            vote_data["vote_message_id"] = vote_msg.id
            # Send results embed and store message ID
            results_embed = discord.Embed(
                title=f"🗳️ Live Vote Results: {self.vote_title}",
                description=self.vote_question,
                color=discord.Color.purple()
            )
            if close_time_text:
                results_embed.set_footer(text=close_time_text)
            results_msg = await results_channel.send(embed=results_embed) if results_channel else None
            vote_data["results_message_id"] = results_msg.id if results_msg else None
            # Store vote by vote_id
            active_votes[interaction.guild.id][self.vote_id] = vote_data
            # Only send *one* response to the interaction to avoid "Unknown interaction" or "already acknowledged" errors
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Vote created!", ephemeral=True)
            else:
                try:
                    await interaction.followup.send("✅ Vote created!", ephemeral=True)
                except Exception:
                    pass
            self.stop()
            # Schedule vote end if timer is set
            if duration_minutes:
                self.bot.loop.create_task(self._auto_end_vote(interaction.guild.id, self.vote_id, duration_minutes, interaction.user))

        async def _auto_end_vote(self, guild_id, vote_id, duration_minutes, author):
            await asyncio.sleep(duration_minutes * 60)
            bot = self.bot
            guild = bot.get_guild(guild_id)
            if not guild:
                return
            dummy_interaction = type("Dummy", (), {"guild": guild, "user": author, "response": type("Resp", (), {"defer": lambda *a, **k: None})(), "followup": type("Follow", (), {"send": lambda *a, **k: None})()})()
            cog = bot.get_cog("VoteCog")
            if cog:
                await cog._finalize_vote(dummy_interaction, vote_id)

    async def _finalize_vote(self, interaction: discord.Interaction, vote_id: int):
        await interaction.response.defer(ephemeral=True)
        votes_dict = active_votes.get(interaction.guild.id, {})
        vote_data = votes_dict.get(vote_id)
        if not vote_data:
            await interaction.followup.send("❌ No active vote found.", ephemeral=True)
            return
        try:
            guild = interaction.guild
            results_channel = guild.get_channel(vote_data.get("results_channel_id"))
            vote_channel = guild.get_channel(vote_data.get("vote_channel_id"))
            vote_message_id = vote_data.get("vote_message_id")
            options = vote_data["options"]
            votes = vote_data["votes"]
            eligible_roles = [guild.get_role(rid) for rid in vote_data.get("eligible_role_ids", [])]
            eligible_members = set()
            for role in eligible_roles:
                eligible_members.update([m for m in role.members if not m.bot])
            voted_user_ids = set(votes.keys())
            didnt_vote = [m.display_name for m in eligible_members if m.id not in voted_user_ids]
            who_voted_what = {str(idx): [] for idx in range(len(options))}
            for user_id, vote_val in votes.items():
                member = guild.get_member(user_id)
                if member:
                    if isinstance(vote_val, list):
                        for idx in vote_val:
                            who_voted_what[str(idx)].append(member.display_name)
                    else:
                        who_voted_what[str(vote_val)].append(member.display_name)
            embed = discord.Embed(
                title=f"🗳️ Vote Results: {vote_data.get('title', '')}",
                description=vote_data.get("question", ""),
                color=discord.Color.green()
            )
            total_votes = len(voted_user_ids)
            embed.add_field(
                name="📊 Total Vote Tally",
                value=f"Total votes cast: {total_votes}/{len(eligible_members)}",
                inline=False
            )
            for i, option in enumerate(options):
                count = len(who_voted_what[str(i)])
                voters = who_voted_what[str(i)]
                voter_list = ", ".join(voters) if voters else "None"
                embed.add_field(
                    name=f"{option} - {count} vote(s)",
                    value=voter_list,
                    inline=False
                )
            if didnt_vote:
                embed.add_field(
                    name="❌ Did Not Vote",
                    value=", ".join(didnt_vote),
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Participation",
                    value="Everyone voted!",
                    inline=False
                )
            # Edit the results message for this vote only
            results_message_id = vote_data.get("results_message_id")
            if results_message_id:
                try:
                    msg = await results_channel.fetch_message(results_message_id)
                    await msg.edit(embed=embed)
                except Exception:
                    await results_channel.send(embed=embed)
            else:
                await results_channel.send(embed=embed)
            # Remove voting buttons from the original vote message
            if vote_channel and vote_message_id:
                try:
                    vote_msg = await vote_channel.fetch_message(vote_message_id)
                    await vote_msg.edit(view=None)
                except Exception:
                    pass
            # Remove this vote from active_votes
            del active_votes[interaction.guild.id][vote_id]
            await interaction.followup.send(
                f"✅ Vote ended! Results posted in {results_channel.mention}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error ending vote: {e}", ephemeral=True)
            logger.error(f"Vote ending error: {e}")

    class VoteButtonsView(discord.ui.View):
        def __init__(self, options, eligible_roles, guild_id, vote_id):
            super().__init__(timeout=3600)
            self.options = options
            self.eligible_roles = eligible_roles
            self.guild_id = guild_id
            self.vote_id = vote_id
            # Discord only allows 5 items per row, and a max of 5 rows (0-4)
            for i, option in enumerate(options[:10]):
                row = 0 if i < 5 else 1
                safe_label = f"{i+1}️⃣ {option[:40]}" if len(option) > 40 else f"{i+1}️⃣ {option}"
                if len(safe_label) > 45:
                    safe_label = safe_label[:45]
                button = discord.ui.Button(
                    label=safe_label,
                    style=discord.ButtonStyle.primary,
                    row=row,
                    custom_id=f"vote_{guild_id}_{i}"
                )
                button.callback = self.create_vote_callback(i)
                self.add_item(button)

        def create_vote_callback(self, option_index):
            async def vote_callback(interaction: discord.Interaction):
                # Only eligible roles can vote
                member = interaction.user
                if not any(role in member.roles for role in self.eligible_roles):
                    await interaction.response.send_message("❌ You are not eligible to vote.", ephemeral=True)
                    return
                guild_id = self.guild_id
                votes_dict = active_votes.get(guild_id, {})
                vote_data = votes_dict.get(self.vote_id)
                if not vote_data:
                    await interaction.response.send_message("❌ No active vote found.", ephemeral=True)
                    return
                user_id = member.id
                # Anonymous voting: store only user_id and option index
                allow_changes = vote_data.get("allow_changes", False)
                already_voted = user_id in vote_data["votes"]
                if already_voted and not allow_changes:
                    await interaction.response.send_message("❌ You have already voted and changes are not allowed.", ephemeral=True)
                    return
                vote_data["votes"][user_id] = option_index
                active_votes[guild_id][self.vote_id] = vote_data
                await interaction.response.send_message(f"✅ Your vote for option {option_index+1} has been recorded anonymously.", ephemeral=True)
                # Update results message in mod channel
                await self.update_results_message(interaction, vote_data)
            return vote_callback

        async def update_results_message(self, interaction, vote_data):
            guild = interaction.guild
            results_channel_id = vote_data.get("results_channel_id")
            results_message_id = vote_data.get("results_message_id")
            if not results_channel_id or not results_message_id:
                return
            results_channel = guild.get_channel(results_channel_id)
            if not results_channel:
                return
            options = vote_data["options"]
            votes = vote_data["votes"]
            eligible_roles = [guild.get_role(rid) for rid in vote_data.get("eligible_role_ids", [])]
            eligible_members = set()
            for role in eligible_roles:
                eligible_members.update([m for m in role.members if not m.bot])
            voted_user_ids = set(votes.keys())
            didnt_vote = [m.display_name for m in eligible_members if m.id not in voted_user_ids]
            who_voted_what = {str(idx): [] for idx in range(len(options))}
            for user_id, vote_val in votes.items():
                member = guild.get_member(user_id)
                if member:
                    who_voted_what[str(vote_val)].append(member.display_name)
            embed = discord.Embed(
                title=f"🗳️ Live Vote Results: {vote_data.get('title', '')}",
                description=vote_data.get("question", ""),
                color=discord.Color.purple()
            )
            total_votes = len(voted_user_ids)
            embed.add_field(
                name="📊 Total Vote Tally",
                value=f"Total votes cast: {total_votes}/{len(eligible_members)}",
                inline=False
            )
            for i, option in enumerate(options):
                count = len(who_voted_what[str(i)])
                voters = who_voted_what[str(i)]
                voter_list = ", ".join(voters) if voters else "None"
                embed.add_field(
                    name=f"{option} - {count} vote(s)",
                    value=voter_list,
                    inline=False
                )
            if didnt_vote:
                embed.add_field(
                    name="❌ Did Not Vote",
                    value=", ".join(didnt_vote),
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Participation",
                    value="Everyone voted!",
                    inline=False
                )
            # Edit only this vote's results message
            try:
                msg = await results_channel.fetch_message(results_message_id)
                await msg.edit(embed=embed)
            except Exception:
                await results_channel.send(embed=embed)

    @app_commands.command(name="endvote", description="End the current vote and post results.")
    async def endvote(self, interaction: discord.Interaction):
        if not is_mod(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return
        guild_votes = active_votes.get(interaction.guild.id, {})
        if not guild_votes:
            await interaction.response.send_message("❌ No active votes found.", ephemeral=True)
            return

        class EndVoteSelect(discord.ui.View):
            def __init__(self, votes_dict, cog):
                super().__init__(timeout=60)
                self.cog = cog
                options = [
                    discord.SelectOption(
                        label=f"{v['title']} (Started: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(v['created_at']))})",
                        value=str(vote_id)
                    )
                    for vote_id, v in votes_dict.items()
                ]
                self.select = discord.ui.Select(
                    placeholder="Select a vote to end...",
                    options=options,
                    min_values=1,
                    max_values=1
                )
                self.select.callback = self.select_callback
                self.add_item(self.select)

            async def select_callback(self, select_interaction: discord.Interaction):
                vote_id = int(self.select.values[0])
                # Only acknowledge the interaction ONCE
                if not select_interaction.response.is_done():
                    await select_interaction.response.edit_message(content="Ending vote...", view=self)
                else:
                    try:
                        await select_interaction.followup.send("Ending vote...", ephemeral=True)
                    except Exception:
                        pass
                await self.cog._finalize_vote(select_interaction, vote_id)
                # Optionally disable the select after ending
                for item in self.children:
                    item.disabled = True
                try:
                    await select_interaction.edit_original_response(view=self)
                except Exception:
                    pass

        await interaction.response.send_message(
            "Select which vote to end:",
            ephemeral=True,
            view=EndVoteSelect(guild_votes, self)
        )

async def setup(bot):
    await bot.add_cog(VoteCog(bot))
