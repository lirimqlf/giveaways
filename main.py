import discord
from discord.ext import commands, tasks
import asyncio
import json
import random
import datetime
import os
import http.server
import socketserver
from threading import Thread
from dotenv import load_dotenv

# Create a simple HTTP server for Render.com health checks
class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Discord Giveaway Bot is running!')

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    handler = SimpleHTTPRequestHandler
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving health check endpoint at port {port}")
        httpd.serve_forever()

# Load environment variables
load_dotenv()

# Bot configuration
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

prefix = os.getenv('COMMAND_PREFIX', '+')
bot = commands.Bot(command_prefix=prefix, intents=intents)

# For storing active giveaways
active_giveaways = {}

# Define the path for giveaways.json
GIVEAWAYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'giveaways.json')

# Load giveaways from file to persist across restarts
def load_giveaways():
    try:
        with open(GIVEAWAYS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

# Save giveaways to file
def save_giveaways():
    try:
        with open(GIVEAWAYS_FILE, 'w') as f:
            json.dump(active_giveaways, f)
    except PermissionError:
        print(f"Warning: Permission denied when writing to {GIVEAWAYS_FILE}. Giveaway data won't persist.")
    except Exception as e:
        print(f"Error saving giveaways: {e}")

@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user}')
    global active_giveaways
    active_giveaways = load_giveaways()
    check_giveaways.start()
    
    # Set bot status
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, 
        name="for giveaways"
    ))

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.select(
        placeholder="Make a choice",
        options=[
            discord.SelectOption(label="Modify duration", description="Set the giveaway duration", emoji="⏱️"),
            discord.SelectOption(label="Modify channel", description="Choose the channel for the giveaway", emoji="🏷️"),
            discord.SelectOption(label="Modify forced winner", description="Choose a forced winner", emoji="👑"),
            discord.SelectOption(label="Remove forced winner", description="Remove the forced winner", emoji="👑"),
            discord.SelectOption(label="Modify required role", description="Set required role to participate", emoji="☀️"),
            discord.SelectOption(label="Remove required role", description="Remove the required role", emoji="🌞"),
            discord.SelectOption(label="Modify number of winners", description="Choose the number of winners", emoji="👥"),
            discord.SelectOption(label="Modify reaction", description="Choose the reaction for the giveaway", emoji="⭐"),
            discord.SelectOption(label="Modify prize", description="Set the giveaway prize", emoji="🎁"),
        ]
    )
    async def select_option(self, interaction: discord.Interaction, select: discord.ui.Select):
        option = select.values[0]
        await interaction.response.send_message(f"Selected: {option}", ephemeral=True)
        
        # Store the current option in the user's state
        user_id = str(interaction.user.id)
        if user_id not in user_states:
            user_states[user_id] = {}
        user_states[user_id]['current_option'] = option
        
        if option == "Modify duration":
            await interaction.followup.send("Please enter the duration in the format 1h, 2d, etc.", ephemeral=True)
        elif option == "Modify channel":
            await interaction.followup.send("Please mention the channel or provide the channel ID.", ephemeral=True)
        elif option == "Modify forced winner":
            await interaction.followup.send("Please mention the user or provide the user ID for the forced winner.", ephemeral=True)
        elif option == "Remove forced winner":
            user_states[user_id]['forced_winner'] = None
            await interaction.followup.send("Forced winner has been removed.", ephemeral=True)
        elif option == "Modify required role":
            await interaction.followup.send("Please mention the role or provide the role ID.", ephemeral=True)
        elif option == "Remove required role":
            user_states[user_id]['required_role'] = None
            await interaction.followup.send("Required role has been removed.", ephemeral=True)
        elif option == "Modify number of winners":
            await interaction.followup.send("Please enter the number of winners.", ephemeral=True)
        elif option == "Modify reaction":
            await interaction.followup.send("Please enter the emoji to use for the giveaway reaction.", ephemeral=True)
        elif option == "Modify prize":
            await interaction.followup.send("Please enter the prize for the giveaway.", ephemeral=True)

    @discord.ui.button(label="Validate", style=discord.ButtonStyle.green, custom_id="validate_button", emoji="✅")
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in user_states or 'duration' not in user_states[user_id]:
            await interaction.response.send_message("Please set at least the duration before validating.", ephemeral=True)
            return
        
        # Create the giveaway
        try:
            await create_giveaway(interaction, user_states[user_id])
        except Exception as e:
            await interaction.response.send_message(f"Error creating giveaway: {e}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_button", emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id in user_states:
            del user_states[user_id]
        await interaction.response.send_message("Giveaway creation cancelled.", ephemeral=True)

# Dictionary to store user states during configuration
user_states = {}

@bot.command(name="giveaway")
async def giveaway(ctx):
    """Start configuring a giveaway"""
    user_id = str(ctx.author.id)
    if user_id not in user_states:
        user_states[user_id] = {
            'duration': '1h',
            'channel': ctx.channel.id,
            'forced_winner': None,
            'required_role': None,
            'winners_count': 1,
            'reaction': '🎉',
            'prize': 'Giveaway Prize'
        }
    
    view = GiveawayView()
    
    embed = discord.Embed(
        title="Giveaway Configuration",
        description="Use the dropdown to configure your giveaway.",
        color=discord.Color(0xffffff)
    )
    embed.add_field(name="Duration", value=user_states[user_id].get('duration', 'Not set'), inline=True)
    embed.add_field(name="Channel", value=f"<#{user_states[user_id].get('channel', ctx.channel.id)}>", inline=True)
    embed.add_field(name="Forced Winner", value=f"<@{user_states[user_id]['forced_winner']}>" if user_states[user_id].get('forced_winner') else "Not set", inline=True)
    embed.add_field(name="Required Role", value=f"<@&{user_states[user_id]['required_role']}>" if user_states[user_id].get('required_role') else "Not set", inline=True)
    embed.add_field(name="Winners Count", value=user_states[user_id].get('winners_count', 1), inline=True)
    embed.add_field(name="Reaction", value=user_states[user_id].get('reaction', '🎉'), inline=True)
    embed.add_field(name="Prize", value=user_states[user_id].get('prize', 'Giveaway Prize'), inline=True)
    
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = str(message.author.id)
    if user_id in user_states and 'current_option' in user_states[user_id]:
        option = user_states[user_id]['current_option']
        
        if option == "Modify duration":
            # Validate duration format
            content = message.content.lower()
            if any(time_unit in content for time_unit in ['s', 'm', 'h', 'd']):
                user_states[user_id]['duration'] = content
                await message.channel.send(f"Duration set to {content}", delete_after=5)
            else:
                await message.channel.send("Invalid format. Please use format like 30s, 5m, 2h, 1d", delete_after=5)
        
        elif option == "Modify channel":
            # Try to get channel from mention or ID
            channel_id = message.content.strip()
            if channel_id.startswith('<#') and channel_id.endswith('>'):
                channel_id = channel_id[2:-1]
            
            try:
                channel = message.guild.get_channel(int(channel_id))
                if channel:
                    user_states[user_id]['channel'] = channel.id
                    await message.channel.send(f"Channel set to {channel.mention}", delete_after=5)
                else:
                    await message.channel.send("Channel not found.", delete_after=5)
            except ValueError:
                await message.channel.send("Invalid channel. Please mention a channel or provide a valid ID.", delete_after=5)
        
        elif option == "Modify forced winner":
            # Try to get user from mention or ID
            user_mention = message.content.strip()
            if user_mention.startswith('<@') and user_mention.endswith('>'):
                user_mention = user_mention[2:-1]
                if user_mention.startswith('!'):
                    user_mention = user_mention[1:]
            
            try:
                member = message.guild.get_member(int(user_mention))
                if member:
                    user_states[user_id]['forced_winner'] = member.id
                    await message.channel.send(f"Forced winner set to {member.mention}", delete_after=5)
                else:
                    await message.channel.send("User not found.", delete_after=5)
            except ValueError:
                await message.channel.send("Invalid user. Please mention a user or provide a valid ID.", delete_after=5)
        
        elif option == "Modify required role":
            # Try to get role from mention or ID
            role_mention = message.content.strip()
            if role_mention.startswith('<@&') and role_mention.endswith('>'):
                role_mention = role_mention[3:-1]
            
            try:
                role = message.guild.get_role(int(role_mention))
                if role:
                    user_states[user_id]['required_role'] = role.id
                    await message.channel.send(f"Required role set to {role.mention}", delete_after=5)
                else:
                    await message.channel.send("Role not found.", delete_after=5)
            except ValueError:
                await message.channel.send("Invalid role. Please mention a role or provide a valid ID.", delete_after=5)
        
        elif option == "Modify number of winners":
            try:
                num_winners = int(message.content.strip())
                if num_winners > 0:
                    user_states[user_id]['winners_count'] = num_winners
                    await message.channel.send(f"Number of winners set to {num_winners}", delete_after=5)
                else:
                    await message.channel.send("Number must be greater than 0.", delete_after=5)
            except ValueError:
                await message.channel.send("Please enter a valid number.", delete_after=5)
        
        elif option == "Modify reaction":
            emoji = message.content.strip()
            # Basic emoji validation (simplistic)
            user_states[user_id]['reaction'] = emoji
            await message.channel.send(f"Reaction set to {emoji}", delete_after=5)
        
        elif option == "Modify prize":
            prize = message.content.strip()
            user_states[user_id]['prize'] = prize
            await message.channel.send(f"Prize set to '{prize}'", delete_after=5)
        
        # Delete the user's message to keep the channel clean
        try:
            await message.delete()
        except:
            pass
        
        # Clear the current option after processing
        del user_states[user_id]['current_option']
        
        # Don't process as a command
        return
    
    await bot.process_commands(message)

async def create_giveaway(interaction, config):
    """Create a giveaway with the provided configuration"""
    duration_str = config['duration']
    total_seconds = 0
    
    # Parse the duration string
    if 'd' in duration_str:
        days = int(duration_str.split('d')[0])
        total_seconds += days * 86400
    elif 'h' in duration_str:
        hours = int(duration_str.split('h')[0])
        total_seconds += hours * 3600
    elif 'm' in duration_str:
        minutes = int(duration_str.split('m')[0])
        total_seconds += minutes * 60
    elif 's' in duration_str:
        seconds = int(duration_str.split('s')[0])
        total_seconds += seconds
    
    # Use datetime with timezone info
    end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=total_seconds)
    
    # Get the channel
    channel = interaction.guild.get_channel(config['channel'])
    if not channel:
        await interaction.response.send_message("Invalid channel configuration.", ephemeral=True)
        return
    
    # Create giveaway embed
    embed = discord.Embed(
        title=f"🎁 GIVEAWAY: {config['prize']}",
        description=f"React with {config['reaction']} to enter!\n\n",
        color=discord.Color(0xffffff)
    )
    
    # Add fields
    if config['required_role']:
        role = interaction.guild.get_role(config['required_role'])
        if role:
            embed.description += f"Required Role: {role.mention}\n"
    
    embed.add_field(name="Winners", value=config['winners_count'], inline=True)
    embed.add_field(name="Ends At", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    embed.set_footer(text=f"Giveaway ID: {len(active_giveaways) + 1}")
    
    # Send the giveaway message
    giveaway_msg = await channel.send(embed=embed)
    await giveaway_msg.add_reaction(config['reaction'])
    
    # Store giveaway data
    giveaway_data = {
        'message_id': giveaway_msg.id,
        'channel_id': channel.id,
        'end_time': end_time.timestamp(),
        'winners_count': config['winners_count'],
        'prize': config['prize'],
        'reaction': config['reaction'],
        'required_role': config['required_role'],
        'forced_winner': config['forced_winner'],
        'host_id': interaction.user.id
    }
    
    active_giveaways[str(giveaway_msg.id)] = giveaway_data
    try:
        save_giveaways()
    except Exception as e:
        print(f"Warning: Could not save giveaways: {e}")
    
    # Confirm to the user
    await interaction.response.send_message(f"Giveaway created successfully in {channel.mention}!", ephemeral=True)

@tasks.loop(seconds=15)
async def check_giveaways():
    """Check for ended giveaways"""
    current_time = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for giveaway_id, giveaway_data in list(active_giveaways.items()):
        if current_time >= giveaway_data['end_time']:
            await end_giveaway(giveaway_id, giveaway_data)

async def end_giveaway(giveaway_id, giveaway_data):
    """End a giveaway and pick winners"""
    try:
        channel = bot.get_channel(giveaway_data['channel_id'])
        if not channel:
            print(f"Channel {giveaway_data['channel_id']} not found")
            del active_giveaways[giveaway_id]
            save_giveaways()
            return
        
        try:
            message = await channel.fetch_message(int(giveaway_id))
        except discord.errors.NotFound:
            print(f"Message {giveaway_id} not found")
            del active_giveaways[giveaway_id]
            save_giveaways()
            return
        
        # Get reaction users
        reaction = None
        for msg_reaction in message.reactions:
            if str(msg_reaction.emoji) == giveaway_data['reaction']:
                reaction = msg_reaction
                break
        
        if not reaction:
            await channel.send("Could not find the giveaway reaction. No winners selected.")
            del active_giveaways[giveaway_id]
            save_giveaways()
            return
        
        users = []
        async for user in reaction.users():
            if not user.bot:
                # Check for required role if any
                if giveaway_data['required_role']:
                    member = channel.guild.get_member(user.id)
                    if member and any(role.id == giveaway_data['required_role'] for role in member.roles):
                        users.append(user)
                else:
                    users.append(user)
        
        winners = []
        
        # Add forced winner if any
        if giveaway_data['forced_winner']:
            forced_user = channel.guild.get_member(giveaway_data['forced_winner'])
            if forced_user:
                winners.append(forced_user)
        
        # Randomly select remaining winners
        remaining_winners = giveaway_data['winners_count'] - len(winners)
        if remaining_winners > 0 and users:
            # Remove forced winners from the pool
            eligible_users = [u for u in users if u.id not in [w.id for w in winners]]
            winners.extend(random.sample(eligible_users, min(remaining_winners, len(eligible_users))))
        
        # Update embed to show that the giveaway has ended
        embed = message.embeds[0]
        embed.color=discord.Color(0xffffff)
        embed.description = f"Giveaway ended!\n\n"
        
        if giveaway_data['required_role']:
            role = channel.guild.get_role(giveaway_data['required_role'])
            if role:
                embed.description += f"Required Role: {role.mention}\n"
        
        if winners:
            winners_text = ", ".join([winner.mention for winner in winners])
            embed.description += f"Winners: {winners_text}"
            
            # Send congratulation message
            congrats_message = f"🎉 Congratulations {winners_text}! You won **{giveaway_data['prize']}**!"
            await channel.send(congrats_message)
        else:
            embed.description += "No valid participants. No winners selected."
            await channel.send(f"No valid participants for the giveaway: **{giveaway_data['prize']}**")
        
        await message.edit(embed=embed)
        
        # Remove from active giveaways
        del active_giveaways[giveaway_id]
        save_giveaways()
    
    except Exception as e:
        print(f"Error ending giveaway {giveaway_id}: {e}")

@bot.command(name="reroll")
@commands.has_permissions(manage_messages=True)
async def reroll(ctx, message_id: int = None):
    """Reroll a giveaway to pick new winners"""
    if message_id is None:
        await ctx.send("Please provide a message ID. Usage: `+reroll [message_id]`")
        return
        
    try:
        # Check if the message exists in the current channel
        try:
            message = await ctx.channel.fetch_message(message_id)
        except discord.errors.NotFound:
            await ctx.send("Could not find that message in this channel.")
            return
        
        # Check if it's a giveaway message (simple check)
        if not message.embeds or "GIVEAWAY" not in message.embeds[0].title:
            await ctx.send("That doesn't seem to be a giveaway message.")
            return
        
        # Get reaction users
        reaction = None
        for msg_reaction in message.reactions:
            reaction_emoji = str(msg_reaction.emoji)
            # Try to find the giveaway reaction (default is 🎉 but could be customized)
            if reaction_emoji in ["🎉", "🎊", "🎁", "🏆", "🥇"]:
                reaction = msg_reaction
                break
        
        if not reaction:
            await ctx.send("Could not find a valid giveaway reaction.")
            return
        
        users = []
        async for user in reaction.users():
            if not user.bot:
                users.append(user)
        
        if not users:
            await ctx.send("No participants found.")
            return
        
        # Pick a random winner
        winner = random.choice(users)
        prize = message.embeds[0].title.split("GIVEAWAY:")[1].strip() if len(message.embeds[0].title.split("GIVEAWAY:")) > 1 else "the prize"
        
        # Send the result
        await ctx.send(f"🎉 The new winner is {winner.mention}! Congratulations, you won **{prize}**!")
    
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@bot.command(name="cancel_giveaway")
@commands.has_permissions(manage_messages=True)
async def cancel_giveaway(ctx, message_id: int = None):
    """Cancel an active giveaway"""
    if message_id is None:
        await ctx.send("Please provide a message ID. Usage: `+cancel_giveaway [message_id]`")
        return
        
    str_message_id = str(message_id)
    if str_message_id in active_giveaways:
        try:
            # Get the message
            channel_id = active_giveaways[str_message_id]['channel_id']
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                    if message:
                        # Update the embed
                        embed = message.embeds[0]
                        embed.color=discord.Color(0xffffff)
                        embed.description = "This giveaway has been cancelled."
                        await message.edit(embed=embed)
                except discord.errors.NotFound:
                    await ctx.send("Message not found, but giveaway will be removed from database.")
            
            # Remove from active giveaways
            del active_giveaways[str_message_id]
            save_giveaways()
            await ctx.send("Giveaway cancelled successfully.")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")
    else:
        await ctx.send("No active giveaway found with that ID.")

@bot.command(name="list_giveaways")
@commands.has_permissions(manage_messages=True)
async def list_giveaways(ctx):
    """List all active giveaways"""
    if not active_giveaways:
        await ctx.send("No active giveaways.")
        return
    
    embed = discord.Embed(
        title="Active Giveaways",
        color=discord.Color(0xffffff)
    )
    
    for giveaway_id, giveaway_data in active_giveaways.items():
        channel = bot.get_channel(giveaway_data['channel_id'])
        channel_name = channel.name if channel else "Unknown channel"
        
        embed.add_field(
            name=f"Prize: {giveaway_data['prize']}",
            value=f"ID: {giveaway_id}\nChannel: #{channel_name}\nEnds: <t:{int(giveaway_data['end_time'])}:R>",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    # Start web server in a separate thread
    print("Starting web server for health checks...")
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True  # This ensures the thread will close when the main program exits
    server_thread.start()
    
    # Run the Discord bot
    print("Starting Discord Giveaway Bot...")
    try:
        TOKEN = os.getenv('DISCORD_TOKEN')
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        print("Invalid token. Please check your token and try again.")
    except Exception as e:
        print(f"Error starting bot: {e}")
