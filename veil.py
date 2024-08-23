import discord
from discord.ext import commands
import asyncio
import aiosqlite
import numpy as np
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageSequence 
import io
import aiohttp
import requests
import re
from discord.ui import Button, View
from itertools import cycle
from io import BytesIO

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True
intents.guilds = True
intents.messages = True
intents.emojis = True

bot = commands.Bot(command_prefix='!', intents=intents)

BOT_OWNER_ID = 515082676559151114
OWNER_ID = 515082676559151114  # Replace with the actual Discord user ID of the owner
recently_welcomed={}
recently_leveled_up = {}
muted_channels = {}
purging_channels = {}


# Database setup
async def setup_db():
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS modlogs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, reason TEXT, timestamp TEXT)""")
        await db.commit()
        await db.execute("""CREATE TABLE IF NOT EXISTS emojis (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, server_id INTEGER)""")
        await db.commit()
        await db.execute("""CREATE TABLE IF NOT EXISTS autoreact (keyword TEXT PRIMARY KEY, emoji TEXT)""")
        await db.commit()
        await db.execute("""CREATE TABLE IF NOT EXISTS autoreply (keyword TEXT PRIMARY KEY, response TEXT)""")
        await db.commit()
        await db.execute("""CREATE TABLE IF NOT EXISTS userreplies (user_id INTEGER PRIMARY KEY, response TEXT)""")
        await db.commit()
        await db.execute("""CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, exp INTEGER, level INTEGER)""")
        await db.commit()

@bot.event
async def on_ready():
    await setup_db()
    print(f'Logged in as {bot.user}')

async def get_gif(action):
    url = f"https://api.otakugifs.xyz/gif?reaction={action}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data['url']
            else:
                return None

# Ban Command
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await log_action(member.id, "Ban", reason)
    await ctx.send(f'{member.mention} has been banned for {reason}')

@bot.command(name='unban')
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user_info: str):
    try:
        # First try to treat the user_info as a user ID
        user_id = int(user_info)
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f'Unbanned {user.name}')
        return
    except ValueError:
        # If the user_info is not a valid ID, treat it as a username
        pass
    except discord.NotFound:
        await ctx.send(f"User ID {user_info} not found.")
        return

    # If the user_info is a username
    banned_users = [entry async for entry in ctx.guild.bans()]
    for ban_entry in banned_users:
        user = ban_entry.user
        if user.name.lower() == user_info.lower():
            await ctx.guild.unban(user)
            await ctx.send(f'Unbanned {user.name}')
            return

    await ctx.send(f'User {user_info} not found in the ban list.')

# Kick Command
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await log_action(member.id, "Kick", reason)
    await ctx.send(f'{member.mention} has been kicked for {reason}')

# Mute Command
@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, time: int, *, reason=None):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not role:
        role = await ctx.guild.create_role(name="Muted")

    for channel in ctx.guild.channels:
        await channel.set_permissions(role, speak=False, send_messages=False)

    await member.add_roles(role)
    await log_action(member.id, "Mute", reason)
    await ctx.send(f'{member.mention} has been muted for {time} seconds for {reason}')
    await asyncio.sleep(time)
    await member.remove_roles(role)
    await ctx.send(f'{member.mention} has been unmuted.')

# Unmute Command
@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    await member.remove_roles(role)
    await log_action(member.id, "Unmute", "N/A")
    await ctx.send(f'{member.mention} has been unmuted.')

# Warn Command
@bot.command()
@commands.has_permissions(manage_roles=True)
async def warn(ctx, member: discord.Member, *, reason=None):
    await log_action(member.id, "Warn", reason)
    await ctx.send(f'{member.mention} has been warned for {reason}')

# Clear Command
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount)
    await ctx.send(f'{amount} messages have been cleared.')

# Modlogs Command
@bot.command()
async def modlogs(ctx, member: discord.Member):
    async with aiosqlite.connect("bot_data.db") as db:
        cursor = await db.execute("SELECT action, reason, timestamp FROM modlogs WHERE user_id = ?", (member.id,))
        logs = await cursor.fetchall()
        if logs:
            log_text = '\n'.join([f"{action} - {reason} at {timestamp}" for action, reason, timestamp in logs])
            await ctx.send(f'Moderation logs for {member.mention}:\n{log_text}')
        else:
            await ctx.send(f'No moderation logs found for {member.mention}.')

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lockdown(ctx, duration: int = None):
    channel = ctx.channel
    everyone_role = ctx.guild.default_role

    try:
        # Get current permissions for the @everyone role
        current_permissions = channel.overwrites_for(everyone_role)

        # Only change permissions if they are currently allowed
        if current_permissions.send_messages is not False:
            # Deny sending messages for everyone
            await channel.set_permissions(everyone_role, send_messages=False)
            await ctx.send(f"🔒 Channel locked down. No one can send messages.")

            # Handle duration if provided
            if duration:
                await ctx.send(f"Lockdown will last for {duration} seconds.")
                await asyncio.sleep(duration)
                # Automatically unlock the channel after the duration
                await channel.set_permissions(everyone_role, send_messages=True)
                await ctx.send("🔓 Lockdown ended. Channel is now unlocked.")
        else:
            await ctx.send("🔒 Channel is already locked down.")
            
    except discord.Forbidden:
        await ctx.send("🚫 I don't have permission to lock down the channel.")
    except discord.HTTPException as e:
        await ctx.send(f"⚠️ An error occurred: {e}")

@lockdown.error
async def lockdown_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Please provide a valid duration in seconds.")
    else:
        await ctx.send("An error occurred while trying to lock down the channel.")

# Slowmode Command
@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f'Slowmode set to {seconds} seconds.')

# Stop Slowmode Command
@bot.command()
@commands.has_permissions(manage_channels=True)
async def stopslowmode(ctx):
    await ctx.channel.edit(slowmode_delay=0)
    await ctx.send('Slowmode has been disabled.')

@bot.command()
@commands.has_permissions(manage_channels=True)
async def stoplockdown(ctx):
    channel = ctx.channel
    everyone_role = ctx.guild.default_role
    
    try:
        # Get current permissions for the @everyone role
        current_permissions = channel.overwrites_for(everyone_role)
        
        # Only change permissions if they are currently restricted
        if not current_permissions.send_messages:
            # Allow everyone to send messages again
            await channel.set_permissions(everyone_role, send_messages=True)
            await ctx.send("🔓 Channel unlocked. Everyone can send messages again.")
        else:
            await ctx.send("🔓 Channel is already unlocked.")
            
    except discord.Forbidden:
        await ctx.send("🚫 I don't have permission to unlock the channel.")
    except discord.HTTPException as e:
        await ctx.send(f"⚠️ An error occurred: {e}")

@stoplockdown.error
async def stoplockdown_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to use this command.")
    else:
        await ctx.send("An error occurred while trying to unlock the channel.")

# Command for manual channel unlock in case something goes wrong
@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlockchannel(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel  # If no channel is specified, use the current one
    overwrites = channel.overwrites
    success = True

    for role, overwrite in overwrites.items():
        if isinstance(role, discord.Role) and overwrite.send_messages is False:
            try:
                await channel.set_permissions(role, send_messages=True)
                await asyncio.sleep(0.5)
            except discord.HTTPException as e:
                success = False
                await ctx.send(f"Failed to update permissions for {role.name}: {str(e)}")
                await asyncio.sleep(5)

    if success:
        await ctx.send(f"{channel.mention} has been successfully unlocked.")
    else:
        await ctx.send(f"{channel.mention} unlocking encountered issues. Please check permissions manually.")

# Appoint Mod Command
@bot.command()
@commands.has_permissions(administrator=True)
async def appointmod(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Moderator")
    if not role:
        role = await ctx.guild.create_role(name="Moderator")
    await member.add_roles(role)
    await ctx.send(f'{member.mention} has been appointed as a Moderator.')

# Appoint Admin Command
@bot.command()
@commands.has_permissions(administrator=True)
async def appointadmin(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Admin")
    if not role:
        role = await ctx.guild.create_role(name="Admin")
    await member.add_roles(role)
    await ctx.send(f'{member.mention} has been appointed as an Admin.')

# Remove Mod Command
@bot.command()
@commands.has_permissions(administrator=True)
async def removemod(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Moderator")
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f'{member.mention} has been removed from the Moderator role.')

# Remove Admin Command
@bot.command()
@commands.has_permissions(administrator=True)
async def removeadmin(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Admin")
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f'{member.mention} has been removed from the Admin role.')

# Purge Bot Command
@bot.command()
@commands.has_permissions(manage_messages=True)
async def purgebot(ctx):
    def is_bot(message):
        return message.author == bot.user
    await ctx.channel.purge(limit=100, check=is_bot)
    await ctx.send('All messages from the bot have been deleted.')

@bot.command()
@commands.has_permissions(administrator=True)
async def massping(ctx, member: discord.Member, *, message=None):
    confirmation = await ctx.send(f"Are you sure you want to mass ping {member.mention}? Type 'yes' to confirm or 'no' to cancel.")
    try:
        response = await bot.wait_for('message', check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=30)
        if response.content.lower() == 'yes':
            for channel in ctx.guild.text_channels:
                if channel.permissions_for(member).view_channel and channel.permissions_for(ctx.guild.me).send_messages:
                    ping_message = await channel.send(f'{member.mention} {message}')
                    await asyncio.sleep(1)  # Adjust the delay as needed
                    await ping_message.delete()
            await ctx.send(f'{member.mention} has been mass ghost pinged.')
        else:
            await ctx.send("Mass ping operation cancelled.")
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond. Mass ping operation cancelled.")


# Mass Ping List Command
@bot.command()
@commands.has_permissions(administrator=True)
async def masspinglist(ctx):
    roles = [role for role in ctx.guild.roles if role.permissions.mention_everyone]
    role_mentions = ', '.join([role.mention for role in roles])
    await ctx.send(f'Roles that can be mass pinged: {role_mentions}')

# Auto-reply command
@bot.command()
@commands.has_permissions(administrator=True)
async def setautoreply(ctx, keyword: str, *, response: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("INSERT OR REPLACE INTO autoreply (keyword, response) VALUES (?, ?)", (keyword, response))
        await db.commit()
    await ctx.send(f'Auto-reply for "{keyword}" set to: "{response}"')

# Auto-react command
@bot.command()
@commands.has_permissions(administrator=True)
async def setautoreact(ctx, keyword: str, emoji: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("INSERT OR REPLACE INTO autoreact (keyword, emoji) VALUES (?, ?)", (keyword, emoji))
        await db.commit()
    await ctx.send(f'Auto-react for "{keyword}" set to: "{emoji}"')

# Auto-reply command for specific users
@bot.command()
@commands.has_permissions(administrator=True)
async def setuserreply(ctx, member: discord.Member, *, response: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("INSERT OR REPLACE INTO userreplies (user_id, response) VALUES (?, ?)", (member.id, response))
        await db.commit()
    await ctx.send(f'Auto-reply for {member.mention} set to: "{response}"')

# Remove Auto-reply Command
@bot.command()
@commands.has_permissions(administrator=True)
async def removeautoreply(ctx, keyword: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("DELETE FROM autoreply WHERE keyword = ?", (keyword,))
        await db.commit()
    await ctx.send(f'Auto-reply for "{keyword}" has been removed.')

# Remove Auto-react Command
@bot.command()
@commands.has_permissions(administrator=True)
async def removeautoreact(ctx, keyword: str):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("DELETE FROM autoreact WHERE keyword = ?", (keyword,))
        await db.commit()
    await ctx.send(f'Auto-react for "{keyword}" has been removed.')

# Remove User Auto-reply Command
@bot.command()
@commands.has_permissions(administrator=True)
async def removeuserreply(ctx, member: discord.Member):
    async with aiosqlite.connect("bot_data.db") as db:
        await db.execute("DELETE FROM userreplies WHERE user_id = ?", (member.id,))
        await db.commit()
    await ctx.send(f'Auto-reply for {member.mention} has been removed.')

#Steal emojis 
class EmojiStealView(View):
    def __init__(self, emojis):
        super().__init__(timeout=None)
        self.emojis = emojis
        self.page = 0
        self.max_pages = len(emojis) - 1
        self.status = None  # To store the status of emoji stealing

    async def update_message(self, interaction):
        emoji = self.emojis[self.page]
        color = discord.Color.blue()  # Default color for the embed border

        if self.status == "success":
            color = discord.Color.green()  # Green for successful emoji stealing
            status_text = "Emoji stolen successfully"
        elif self.status == "failure":
            color = discord.Color.red()  # Red for failure
            status_text = "Failed to steal emoji"
        else:
            status_text = ""

        embed = discord.Embed(title="Enlarged Emoji!", description=f"**EMOJI:** {emoji.name}\n**ID:** {emoji.id}", color=color)
        embed.set_image(url=str(emoji.url))
        embed.set_footer(text=f"{status_text} | Page {self.page + 1}/{len(self.emojis)}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='◀', style=discord.ButtonStyle.primary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        if self.page > 0:
            self.page -= 1
            self.status = None  # Reset status when navigating
            await self.update_message(interaction)

    @discord.ui.button(label='Steal', style=discord.ButtonStyle.success)
    async def steal(self, interaction: discord.Interaction, button: Button):
        emoji = self.emojis[self.page]
        guild = interaction.guild
        if guild is None:
            self.status = "failure"
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            await self.update_message(interaction)
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(emoji.url)) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        await guild.create_custom_emoji(name=emoji.name, image=image_data)
                        self.status = "success"
                    else:
                        self.status = "failure"
            await self.update_message(interaction)
        except discord.HTTPException as e:
            self.status = "failure"
            await self.update_message(interaction)

    @discord.ui.button(label='▶', style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: Button):
        if self.page < self.max_pages:
            self.page += 1
            self.status = None  # Reset status when navigating
            await self.update_message(interaction)

@bot.command(name='steal')
async def steal(ctx):
    custom_emoji_pattern = re.compile(r'<a?:\w+:\d+>')
    emojis = []

    async for message in ctx.channel.history(limit=15):
        found_emojis = custom_emoji_pattern.findall(message.content)
        for emoji_str in found_emojis:
            emoji_name = emoji_str.split(':')[1]
            emoji_id = int(emoji_str.split(':')[2][:-1])
            is_animated = emoji_str.startswith('<a:')
            partial_emoji = discord.PartialEmoji(name=emoji_name, id=emoji_id, animated=is_animated)
            emojis.append(partial_emoji)

    if not emojis:
        await ctx.send("No emojis found in the last 15 messages.")
        return

    view = EmojiStealView(emojis)
    emoji = emojis[0]  # Display the first emoji initially
    embed = discord.Embed(title="Enlarged Emoji!", description=f"**EMOJI:** {emoji.name}\n**ID:** {emoji.id}", color=discord.Color.blue())
    embed.set_image(url=str(emoji.url))
    embed.set_footer(text=f"Page 1/{len(emojis)}")
    await ctx.send(embed=embed, view=view)




# List Emojis Command
@bot.command()
async def listemojis(ctx):
    emojis = ctx.guild.emojis
    emoji_list = '\n'.join([f'{emoji.name}: {str(emoji)}' for emoji in emojis])
    await ctx.send(f'Custom Emojis:\n{emoji_list}')

# Remove Emoji Command
@bot.command()
@commands.has_permissions(manage_emojis=True)
async def removeemoji(ctx, name: str):
    emoji = discord.utils.get(ctx.guild.emojis, name=name)
    if emoji:
        await emoji.delete()
        await ctx.send(f'Emoji {name} removed.')
        async with aiosqlite.connect("bot_data.db") as db:
            await db.execute("DELETE FROM emojis WHERE name = ?", (name,))
            await db.commit()
    else:
        await ctx.send(f'Emoji {name} not found.')

@bot.event
async def on_member_join(member: discord.Member):
    # Get the current time
    now = datetime.datetime.utcnow()
    
    # Check if the user has been welcomed recently
    if member.id in recently_welcomed:
        last_welcomed = recently_welcomed[member.id]
        # Check if it's been less than 24 hours since the last welcome
        if (now - last_welcomed).total_seconds() < 86400:
            print(f"User {member.display_name} has already been welcomed recently.")
            return

    try:
        # Fetch the user's profile picture
        avatar_url = member.avatar.url
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as response:
                avatar_data = await response.read()

        # Create a circular avatar
        img = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
        h, w = img.size

        # Create a circular mask for the avatar
        mask = Image.new('L', (h, w), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, h, w), fill=255)

        # Apply the mask to the avatar image
        avatar = Image.new('RGBA', img.size)
        avatar.paste(img, (0, 0), mask)

        # Save the circular avatar
        circular_avatar_path = "/workspaces/ddoschan/ddos/dos/result.png"
        avatar.save(circular_avatar_path)

        # Load and process the welcome banner
        banner_path = "/workspaces/ddoschan/ddos/dos/welcome_banner.png"
        img = Image.open(banner_path).convert("RGBA")
        pfp = Image.open(circular_avatar_path).convert("RGBA")

        # Resize and paste user avatar onto the banner
        pfp = pfp.resize((1400, 1400))
        img.paste(pfp, (380, 274), pfp)

        # Add text to the image
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 60)
        except IOError:
            font = ImageFont.load_default()

        welcome_text = f"Welcome to the server, {member.mention}!"
        text_position = (100, 600)
        draw.text(text_position, welcome_text, fill="white", font=font)

        # Save the final welcome image as PNG
        final_image_path = "/workspaces/ddoschan/ddos/dos/welcome.png"
        img.save(final_image_path, format="PNG")

        # Send the text message and the image to the specified channel
        channel = bot.get_channel(1262399368087212062)  # Replace with your channel ID
        if channel:
            # Send the welcome message with the user mention
            await channel.send(f"Welcome {member.mention}!")
            # Send the final welcome image
            await channel.send(file=discord.File(final_image_path))
            print("Welcome message and image sent successfully.")
        else:
            print("Channel not found.")
        
        # Update the recently welcomed dictionary
        recently_welcomed[member.id] = now
        
    except Exception as e:
        print(f"An errorlea occurred: {e}")

@bot.command(name='checkperms')
async def checkperms(ctx):
    permissions = ctx.channel.permissions_for(ctx.guild.me)
    await ctx.send(f"Permissions: {permissions}")

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send('Pong!')


@bot.command()
async def pfp(ctx, user_id: int):
    try:
        response = requests.get(f"https://discord.com/api/v10/users/{user_id}", headers={
            "Authorization": f"Bot {bot.http.token}"
        })
        
        if response.status_code == 200:
            user_data = response.json()
            avatar_id = user_data.get("avatar")
            if avatar_id:
                # Use webp or jpg for higher quality
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_id}.webp?size=2048"
                # Send the image directly
                await ctx.send(avatar_url)
            else:
                await ctx.send("User has no avatar.")
        else:
            await ctx.send("User not found or an error occurred.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")

@bot.command(aliases=['fuck', 'fx', '18+', 'xxx', 'nsfw'])
async def waifu(ctx, amount: int = 1):
    if ctx.author.id != OWNER_ID:
        await ctx.send("You do not have permission to use this command.")
        return

    if amount > 100:
        await ctx.send("You can only request up to 100 images at a time.")
        return

    await ctx.message.delete()
    
    for _ in range(amount):
        try:
            response = requests.get('https://api.waifu.pics/nsfw/waifu')
            data = response.json()
            if 'url' in data:
                image_url = data['url']
                await ctx.send(image_url)
            else:
                await ctx.send("Error fetching NSFW waifu image.")
        except Exception as e:
            print('Error fetching NSFW waifu image:', e)
            await ctx.send("An error occurred while fetching images.")
        
        # Delay to prevent hitting rate limits
        await asyncio.sleep(2)  # Adjust the delay as needed

@bot.command()
@commands.has_permissions(administrator=True)
async def dnd(ctx):
    channel = ctx.channel
    
    if channel.id in purging_channels:
        # Stop purging
        purging_channels[channel.id].stop()
        del purging_channels[channel.id]
        await ctx.send("Automatic message deletion is now disabled in this channel.")
    else:
        # Start purging
        async def clear_channel():
            while channel.id in purging_channels:
                try:
                    await channel.purge(limit=5)  # Adjust the limit as needed
                except discord.Forbidden:
                    await ctx.send("Bot does not have permission to delete messages in this channel.")
                    del purging_channels[channel.id]
                    break
                except discord.HTTPException as e:
                    print(f"Error deleting messages: {e}")
                    del purging_channels[channel.id]
                    break
                await asyncio.sleep(5)  # Wait 5 seconds before next purge
        
        task = bot.loop.create_task(clear_channel())
        purging_channels[channel.id] = task
        await ctx.send("Automatic message deletion is now enabled in this channel.")


@bot.command()
async def kiss(ctx, member: discord.Member = None):
    if member is None:
        await ctx.send('You need to mention someone to kiss!')
        return
    gif_url = await get_gif('kiss')
    if gif_url:
        embed = discord.Embed(description=f'{ctx.author.mention} gives {member.mention} a kiss!')
        embed.set_image(url=gif_url)
        await ctx.send(embed=embed)
    else:
        await ctx.send('Could not fetch a kiss GIF at the moment.')

@bot.command()
async def slap(ctx, member: discord.Member = None):
    if member is None:
        await ctx.send('You need to mention someone to slap!')
        return
    gif_url = await get_gif('slap')
    if gif_url:
        embed = discord.Embed(description=f'{ctx.author.mention} slaps {member.mention}!')
        embed.set_image(url=gif_url)
        await ctx.send(embed=embed)
    else:
        await ctx.send('Could not fetch a slap GIF at the moment.')



# Log action function
async def log_action(user_id, action, reason):
    async with aiosqlite.connect("bot_data.db") as db:
        timestamp = datetime.datetime.now().isoformat()
        await db.execute("INSERT INTO modlogs (user_id, action, reason, timestamp) VALUES (?, ?, ?, ?)",
                         (user_id, action, reason, timestamp))
        await db.commit()

# Run the bot
bot.run('token_here')
