import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv
import http.server
import socketserver
from threading import Thread

# Create a simple HTTP server to keep the bot alive on Render
class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Discord Archive Bot is running!')

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    handler = SimpleHTTPRequestHandler
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving health check endpoint at port {port}")
        httpd.serve_forever()

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')  # Get token from environment variable
ARCHIVE_CATEGORY_ID = int(os.getenv('ARCHIVE_CATEGORY_ID', '1365446198411923506'))
PREFIX = os.getenv('COMMAND_PREFIX', '+')

# Set up intents to access guild information
intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True

# Initialize bot with prefix and intents
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Keep track of archive count
archive_count = 0

@bot.event
async def on_ready():
    print(f'Bot is online and logged in as {bot.user}')
    
    # Determine the current archive count by checking existing channels
    global archive_count
    for guild in bot.guilds:
        archive_category = discord.utils.get(guild.categories, id=ARCHIVE_CATEGORY_ID)
        if archive_category:
            for channel in archive_category.channels:
                if channel.name.startswith('archive-'):
                    try:
                        num = int(channel.name.split('-')[1])
                        archive_count = max(archive_count, num)
                    except (ValueError, IndexError):
                        pass
    print(f'Current archive count: {archive_count}')
    
    # Set bot status
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, 
        name="for channels to archive"
    ))

@bot.command(name='archive')
@commands.has_permissions(manage_channels=True)
async def archive_channel(ctx, channel_id: int):
    """Archive a channel by moving it to the archive category and renaming it"""
    try:
        # Get the channel to archive
        channel_to_archive = bot.get_channel(channel_id)
        if not channel_to_archive:
            await ctx.send(f"Could not find channel with ID {channel_id}")
            return

        # Get the archive category
        archive_category = discord.utils.get(ctx.guild.categories, id=ARCHIVE_CATEGORY_ID)
        if not archive_category:
            await ctx.send(f"Archive category with ID {ARCHIVE_CATEGORY_ID} does not exist")
            return

        # Increment archive count
        global archive_count
        archive_count += 1
        
        # Rename and move channel
        original_name = channel_to_archive.name
        new_name = f"archive-{archive_count}"
        
        await channel_to_archive.edit(name=new_name, category=archive_category)
        
        await ctx.send(f"Channel {original_name} has been archived as {new_name}")
        
    except discord.Forbidden:
        await ctx.send("I don't have permission to archive that channel")
    except discord.HTTPException as e:
        await ctx.send(f"An error occurred: {e}")
    except Exception as e:
        await ctx.send(f"An unexpected error occurred: {e}")

@archive_channel.error
async def archive_channel_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please provide a channel ID. Usage: `+archive [channel id]`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Invalid channel ID. Please provide a valid channel ID.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    else:
        await ctx.send(f"An error occurred: {error}")

# Add a permissions check command
@bot.command(name='check_permissions')
async def check_permissions(ctx):
    """Check the bot's permissions in the current guild"""
    bot_member = ctx.guild.get_member(bot.user.id)
    
    permissions = []
    for perm, value in bot_member.guild_permissions:
        if value:
            permissions.append(perm)
    
    await ctx.send(f"Bot permissions: {', '.join(permissions)}")

# Run the bot
if __name__ == "__main__":
    # Start web server in a separate thread
    print("Starting web server for health checks...")
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True  # This ensures the thread will close when the main program exits
    server_thread.start()
    
    # Run the Discord bot
    print("Starting Discord bot...")
    bot.run(TOKEN)
