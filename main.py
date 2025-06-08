import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
from flask import Flask, jsonify, request
import threading
import os
from datetime import datetime
import io

# 嘗試載入 python-dotenv，如果沒有安裝就跳過
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Flask 設定
app = Flask(__name__)

# Discord Bot 設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# 遊戲資料 (全局變數，現在只在記憶體中，不會自動從文件載入或儲存)
# 每次機器人啟動時，都會重新初始化為這個狀態 (除非透過 /load 手動載入)
game_data = {
    'users': {}, # 這是會動態改變的部分，但會在重啟後清空 (除非手動載入)
    'fish_data': {
        'common': {
            '小魚': {'weight_range': (0.1, 0.5), 'price_per_kg': 10, 'emoji': '🐠'},
            '鯉魚': {'weight_range': (0.3, 1.2), 'price_per_kg': 15, 'emoji': '🐟'},
            '草魚': {'weight_range': (0.5, 1.5), 'price_per_kg': 12, 'emoji': '🐡'}
        },
        'rare': {
            '鯛魚': {'weight_range': (0.8, 2.0), 'price_per_kg': 30, 'emoji': '🐡'},
            '鱸魚': {'weight_range': (1.0, 2.5), 'price_per_kg': 35, 'emoji': '🐟'},
            '石斑魚': {'weight_range': (1.2, 3.0), 'price_per_kg': 40, 'emoji': '🦈'}
        },
        'epic': {
            '鮭魚': {'weight_range': (2.0, 4.0), 'price_per_kg': 60, 'emoji': '🍣'},
            '鮪魚': {'weight_range': (3.0, 6.0), 'price_per_kg': 80, 'emoji': '🐟'},
            '旗魚': {'weight_range': (4.0, 8.0), 'price_per_kg': 100, 'emoji': '🗡️'}
        },
        'legendary': {
            '龍魚': {'weight_range': (5.0, 10.0), 'price_per_kg': 200, 'emoji': '🐉'},
            '鯊魚': {'weight_range': (8.0, 15.0), 'price_per_kg': 250, 'emoji': '🦈'},
            '黃金魚': {'weight_range': (1.0, 3.0), 'price_per_kg': 500, 'emoji': '🌟'}
        },
        'junk': {
            '破鞋': {'weight_range': (0.1, 0.5), 'price_per_kg': 1, 'emoji': '👟'}
        }
    },
    'items': {
        '基本魚竿': {'price': 0, 'catch_bonus': 1.0, 'rare_bonus': 0.0, 'description': '最初始的魚竿，沒有任何加成。'},
        '中級魚竿': {'price': 500, 'catch_bonus': 1.2, 'rare_bonus': 0.1, 'description': '提高釣魚成功率和釣到稀有魚的機率。'},
        '高級魚竿': {'price': 1500, 'catch_bonus': 1.5, 'rare_bonus': 0.2, 'description': '顯著提高釣魚成功率和釣到稀有魚的機率。'},
        '傳說魚竿': {'price': 5000, 'catch_bonus': 2.0, 'rare_bonus': 0.3, 'description': '大幅提高釣魚成功率和釣到傳說魚的機率。'},
        '魚餌': {'price': 50, 'catch_bonus': 1.1, 'rare_bonus': 0.05, 'description': '一次性消耗品，使用後會略微提高釣魚成功率和稀有度機率。'}
    },
    'rarity_rates': {
        'common': 0.6,
        'rare': 0.25,
        'epic': 0.12,
        'legendary': 0.03,
        'junk': 0.1
    }
}

# --- 輔助函數：資料相關 ---
def get_user_data(user_id):
    """獲取或創建用戶資料。資料僅在記憶體中維護。"""
    user_id = str(user_id)
    if user_id not in game_data['users']:
        game_data['users'][user_id] = {
            'money': 100,
            'items': {'基本魚竿': 1},
            'current_rod': '基本魚竿',
            'fish_caught': {},
            'total_catches': 0
        }
    return game_data['users'][user_id]

# --- 遊戲邏輯函數 (不變) ---
def calculate_catch_probability(user_data):
    rod = user_data['current_rod']
    rod_info = game_data['items'].get(rod, game_data['items']['基本魚竿'])

    catch_bonus = rod_info['catch_bonus']
    rare_bonus = rod_info['rare_bonus']

    if '魚餌' in user_data['items'] and user_data['items']['魚餌'] > 0:
        bait_info = game_data['items']['魚餌']
        catch_bonus *= bait_info['catch_bonus']
        rare_bonus += bait_info['rare_bonus']
        user_data['items']['魚餌'] -= 1
        if user_data['items']['魚餌'] <= 0:
            del user_data['items']['魚餌']
        print(f"DEBUG: 使用魚餌，剩餘 {user_data['items'].get('魚餌', 0)} 個")

    return catch_bonus, rare_bonus

def determine_fish_rarity(rare_bonus):
    rates = game_data['rarity_rates'].copy()

    total_boost = rare_bonus
    if total_boost > 0:
        boost_to_legendary = total_boost * 0.4
        boost_to_epic = total_boost * 0.3
        boost_to_rare = total_boost * 0.2

        rates['legendary'] = rates.get('legendary', 0) + boost_to_legendary
        rates['epic'] = rates.get('epic', 0) + boost_to_epic
        rates['rare'] = rates.get('rare', 0) + boost_to_rare

        deductible_amount = (boost_to_legendary + boost_to_epic + boost_to_rare) - (rates['common'] + rates['rare'] + rates['epic'] + rates['legendary'] - sum(game_data['rarity_rates'].values()))
        if deductible_amount > 0:
            deduct_from_common = min(rates.get('common', 0), deductible_amount * 0.7)
            rates['common'] = rates.get('common', 0) - deduct_from_common
            deductible_amount -= deduct_from_common

            deduct_from_junk = min(rates.get('junk', 0), deductible_amount)
            rates['junk'] = rates.get('junk', 0) - deduct_from_junk

    for rarity in rates:
        rates[rarity] = max(0, rates[rarity])

    total_sum = sum(rates.values())
    if total_sum != 0:
        for rarity in rates:
            rates[rarity] /= total_sum
    else:
        rates = {'common': 1.0}

    rand = random.random()
    cumulative = 0

    for rarity, rate in rates.items():
        cumulative += rate
        if rand <= cumulative:
            return rarity

    return 'common'

# --- Discord 機器人事件 ---
@bot.event
async def on_ready():
    print(f'{bot.user} 已連線!')
    try:
        synced_commands = await bot.tree.sync()
        print(f"已同步 {len(synced_commands)} 個斜線指令。")
    except Exception as e:
        print(f"同步指令失敗: {e}")

# --- 斜線指令定義 ---

@bot.tree.command(name='game', description='顯示所有可用的遊戲指令和遊戲說明。')
async def game_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🎣 釣魚遊戲指令", color=0x00ff00)
    commands_text = """
    `/fish` - 開始釣魚
    `/fish_item <魚竿名稱>` - 切換釣魚道具（魚竿），直接輸入名稱
    `/shop` - 查看商店
    `/buy <物品名稱>` - 從商店購買物品
    `/bag` - 查看背包、金錢和釣到的魚
    `/new_game` - 建立新遊戲（重置你的資料）
    `/save` - 將你的遊戲進度保存為 JSON 檔案，以便下載 (此版本不自動保存到檔案)
    `/load` - 上傳你的遊戲進度 JSON 檔案，繼續之前的進度
    """
    game_info_text = """
    **釣魚系統：**
    - 根據魚的稀有度和重量獲得金錢。
    - 使用更好的魚竿可以提高釣魚成功率和稀有魚的機率。
    - 魚餌是一次性消耗品，能提供額外加成。
    **稀有度等級:**
    🟢 普通 (Common)
    🔵 稀有 (Rare)
    🟣 史詩 (Epic)
    🟡 傳說 (Legendary)
    ⚫ 垃圾 (Junk)
    """
    embed.add_field(name="指令列表", value=commands_text, inline=False)
    embed.add_field(name="遊戲說明", value=game_info_text, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='new_game', description='開始一個新遊戲並重置你的進度。')
async def new_game_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_data_before_reset = get_user_data(user_id)

    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="⚠️ 建立新遊戲確認",
        description="這將會重置你的所有遊戲資料。**此操作無法復原！**",
        color=0xff6600
    )
    reset_info = f"""
    💰 金錢: {user_data_before_reset['money']} → 100
    🎣 道具數量: {sum(user_data_before_reset['items'].values())} 個 → 1 個（基本魚竿）
    📊 總釣魚次數: {user_data_before_reset['total_catches']} 次 → 0
    🐟 魚類收藏: {len(user_data_before_reset['fish_caught'])} 種 → 0

    請輸入 `確認重置` 來建立新遊戲，輸入其他任何內容則取消。
    """
    embed.add_field(name="將會重置的資料概覽", value=reset_info, inline=False)
    embed.set_footer(text="你有 30 秒時間回應。")

    await interaction.followup.send(embed=embed, ephemeral=True)

    def check(m):
        return m.author == interaction.user and m.channel == interaction.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=30.0)
        user_input = msg.content.lower().strip()

        if user_input == '確認重置':
            # 重置玩家資料：直接在 memory 中覆蓋
            game_data['users'][user_id] = {
                'money': 100,
                'items': {'基本魚竿': 1},
                'current_rod': '基本魚竿',
                'fish_caught': {},
                'total_catches': 0
            }

            success_embed = discord.Embed(
                title="🎉 新遊戲建立成功!",
                description="你的遊戲資料已重置為初始狀態。",
                color=0x00ff00
            )
            success_embed.add_field(name="初始狀態", value="💰 金錢: 100\n🎣 道具: 基本魚竿 x1\n🐟 釣魚記錄: 0", inline=False)
            success_embed.add_field(name="開始遊戲", value="使用 `/fish` 開始你的釣魚冒險！\n使用 `/game` 查看所有指令。", inline=False)
            await interaction.followup.send(embed=success_embed, ephemeral=False)
        else:
            cancel_embed = discord.Embed(
                title="❌ 已取消建立新遊戲",
                description="你的遊戲資料保持不變。",
                color=0x808080
            )
            await interaction.followup.send(embed=cancel_embed, ephemeral=True)

    except asyncio.TimeoutError:
        timeout_embed = discord.Embed(
            title="⏰ 操作超時",
            description="建立新遊戲已取消，你的資料保持不變。",
            color=0x808080
        )
        await interaction.followup.send(embed=timeout_embed, ephemeral=True)
    except Exception as e:
        error_embed = discord.Embed(
            title="發生錯誤",
            description=f"在建立新遊戲時發生錯誤: {e}",
            color=0xff0000
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)


@bot.tree.command(name='fish', description='開始釣魚！')
async def fish_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    if not user_data['items'] or not user_data['current_rod'] in user_data['items']:
        await interaction.response.send_message("❌ 你沒有任何魚竿！請先到 `/shop` 購買。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    catch_bonus, rare_bonus = calculate_catch_probability(user_data)
    success_rate = min(0.95, 0.7 * catch_bonus)

    initial_fishing_embed = discord.Embed(title="🎣 釣魚中...", description="正在準備魚竿和魚餌...", color=0xffff00)
    initial_fishing_embed.add_field(name="使用道具", value=user_data['current_rod'], inline=True)
    if '魚餌' in user_data['items'] and user_data['items']['魚餌'] > 0:
        initial_fishing_embed.add_field(name="使用魚餌", value="是", inline=True)
    await interaction.edit_original_response(embed=initial_fishing_embed)


    await asyncio.sleep(2)

    if random.random() > success_rate:
        embed = discord.Embed(title="💔 釣魚失敗", color=0xff0000)
        embed.add_field(name="結果", value="什麼都沒釣到...", inline=False)
        await interaction.edit_original_response(embed=embed)
        return

    rarity = determine_fish_rarity(rare_bonus)
    if not game_data['fish_data'].get(rarity):
        rarity = 'common'
    fish_name = random.choice(list(game_data['fish_data'][rarity].keys()))
    fish_info = game_data['fish_data'][rarity][fish_name]

    weight = round(random.uniform(*fish_info['weight_range']), 2)
    price = int(weight * fish_info['price_per_kg'])
    emoji = fish_info.get('emoji', '🐟')

    user_data['money'] += price
    user_data['total_catches'] += 1
    if fish_name not in user_data['fish_caught']:
        user_data['fish_caught'][fish_name] = 0
    user_data['fish_caught'][fish_name] += 1

    rarity_colors = {
        'common': 0x808080, 'rare': 0x0080ff, 'epic': 0x8000ff, 'legendary': 0xffd700, 'junk': 0x404040
    }
    rarity_emojis = {
        'common': '🟢', 'rare': '🔵', 'epic': '🟣', 'legendary': '🟡', 'junk': '⚫'
    }

    result_embed = discord.Embed(title="🎉 釣魚成功!", color=rarity_colors[rarity])
    result_embed.add_field(name="魚類", value=f"{rarity_emojis[rarity]} {fish_name} {emoji}", inline=True)
    result_embed.add_field(name="重量", value=f"{weight} kg", inline=True)
    result_embed.add_field(name="獲得金錢", value=f"💰 {price}", inline=True)
    result_embed.add_field(name="目前金錢", value=f"💰 {user_data['money']}", inline=True)

    await interaction.edit_original_response(embed=result_embed)

@bot.tree.command(name='fish_item', description='切換你的釣魚道具（魚竿），請直接輸入魚竿名稱。')
@app_commands.describe(rod_name='要切換的魚竿名稱 (例如：中級魚竿)')
async def fish_item_command(interaction: discord.Interaction, rod_name: str):
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    # 將輸入的魚竿名稱正規化，方便比對 (移除空白、轉小寫)
    normalized_input_name = rod_name.lower().replace(' ', '')
    found_rod_key = None

    # 檢查用戶背包中是否有這個魚竿
    for item_in_bag in user_data['items'].keys():
        if item_in_bag.lower().replace(' ', '') == normalized_input_name and '魚竿' in item_in_bag:
            found_rod_key = item_in_bag
            break

    if found_rod_key:
        user_data['current_rod'] = found_rod_key
        await interaction.response.send_message(f"✅ 已切換到 **{found_rod_key}**！", ephemeral=False)
    else:
        # 如果用戶背包中沒有這個魚竿，或者輸入的不是魚竿
        await interaction.response.send_message(
            f"❌ 你沒有名為「**{rod_name}**」的魚竿，或者它不是一個魚竿。請檢查 `/bag` 確認你擁有的魚竿。",
            ephemeral=True
        )

@bot.tree.command(name='shop', description='查看商店裡可用的釣魚用品。')
async def shop_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🏪 釣魚用品商店", color=0x00ff00)

    for item, info in game_data['items'].items():
        if item == '基本魚竿':
            continue
        embed.add_field(
            name=f"{item}",
            value=f"價格: 💰{info['price']}\n描述: {info.get('description', '無')}",
            inline=True
        )

    embed.set_footer(text="使用 /buy <物品名稱> 來購買道具。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='buy', description='從商店購買物品。')
@app_commands.describe(item_name='要購買的物品名稱 (例如：高級魚竿)')
async def buy_command(interaction: discord.Interaction, item_name: str):
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    normalized_input_name = item_name.lower().replace(' ', '')
    found_item_key = None
    item_info = None

    for key, info in game_data['items'].items():
        if key.lower().replace(' ', '') == normalized_input_name:
            found_item_key = key
            item_info = info
            break

    if not found_item_key or found_item_key == '基本魚竿':
        await interaction.response.send_message(f"❌ 商店中沒有 **{item_name}** 這個物品。", ephemeral=True)
        return

    price = item_info['price']

    if user_data['money'] >= price:
        user_data['money'] -= price
        if found_item_key not in user_data['items']:
            user_data['items'][found_item_key] = 0
        user_data['items'][found_item_key] += 1

        await interaction.response.send_message(
            f"✅ 成功購買了 **{found_item_key}**！你現在有 💰{user_data['money']} 金錢。",
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"❌ 你的金錢不足！購買 **{found_item_key}** 需要 💰{price}，你只有 💰{user_data['money']}。",
            ephemeral=True
        )

@bot.tree.command(name='bag', description='查看你的背包、金錢和釣到的魚。')
async def bag_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id)

    embed = discord.Embed(title=f"🎒 {interaction.user.display_name} 的背包", color=0x9932cc)
    embed.add_field(name="💰 金錢", value=str(user_data['money']), inline=True)
    embed.add_field(name="🎣 當前魚竿", value=user_data['current_rod'], inline=True)
    embed.add_field(name="📊 總釣魚次數", value=str(user_data['total_catches']), inline=True)

    items_text = ""
    if user_data['items']:
        for item, count in user_data['items'].items():
            items_text += f"{item}: {count}\n"
    else:
        items_text = "無"
    embed.add_field(name="🛠️ 道具", value=items_text, inline=False)

    if user_data['fish_caught']:
        fish_text = ""
        sorted_fish = sorted(user_data['fish_caught'].items(), key=lambda item: item[0])
        for fish, count in sorted_fish:
            fish_rarity = 'common'
            fish_emoji = '🐟'
            for rarity_type, fish_map in game_data['fish_data'].items():
                if fish in fish_map:
                    fish_rarity = rarity_type
                    fish_emoji = fish_map[fish]['emoji']
                    break
            rarity_emojis = {
                'common': '🟢', 'rare': '🔵', 'epic': '🟣', 'legendary': '🟡', 'junk': '⚫'
            }
            fish_text += f"{rarity_emojis.get(fish_rarity, '❓')} {fish}: {count} 條 {fish_emoji}\n"
        embed.add_field(name="🐟 釣到的魚", value=fish_text, inline=False)
    else:
        embed.add_field(name="🐟 釣到的魚", value="你還沒有釣到任何魚。", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='save', description='將你的遊戲進度保存為 JSON 檔案，以便下載。')
async def save_command(interaction: discord.Interaction):
    """保存玩家資料為檔案 (匯出功能)"""
    user_id = str(interaction.user.id)
    player_data = get_user_data(user_id)

    # 為了只保存單一用戶的數據，我們建立一個新的字典
    data_to_save_for_user = {user_id: player_data}
    json_string = json.dumps(data_to_save_for_user, indent=4, ensure_ascii=False)

    file_bytes = io.BytesIO(json_string.encode('utf-8'))

    filename = f'fishing_data_{user_id}.json'
    discord_file = discord.File(file_bytes, filename=filename)

    await interaction.response.send_message(
        f'{interaction.user.mention} 這是你的遊戲進度檔案。請妥善保存！\n'
        '**重要：** 此機器人版本不會自動保存進度。若要恢復，請使用 `/load` 指令。',
        file=discord_file,
        ephemeral=True # 訊息只對使用者可見
    )

@bot.tree.command(name='load', description='上傳你的遊戲進度 JSON 檔案，繼續之前的進度。')
@app_commands.describe(file='請上傳你的 JSON 進度檔案')
async def load_command(interaction: discord.Interaction, file: discord.Attachment):
    user_id = str(interaction.user.id)

    await interaction.response.defer(ephemeral=True)

    if not file.filename.lower().endswith('.json'):
        await interaction.followup.send("❌ 請上傳一個 **.json** 檔案。", ephemeral=True)
        return

    try:
        file_content_bytes = await file.read()
        file_content_str = file_content_bytes.decode('utf-8')
        loaded_data = json.loads(file_content_str)

        if user_id not in loaded_data:
            await interaction.followup.send(
                "❌ 載入的檔案不包含你的遊戲進度！請確保上傳的是你自己的 `/save` 檔案。",
                ephemeral=True
            )
            return

        game_data['users'][user_id] = loaded_data[user_id]

        loaded_player_data = game_data['users'][user_id]
        coins = loaded_player_data.get('money', 0)
        items_count = sum(loaded_player_data.get('items', {}).values())
        fish_types_count = len(loaded_player_data.get('fish_caught', {}))

        await interaction.followup.send(
            f'✅ **{interaction.user.mention}** 你的遊戲進度已成功載入！\n'
            f'你現在有 **💰{coins}** 金錢，**🎣 {items_count}** 個道具，並釣過 **🐟 {fish_types_count}** 種魚。',
            ephemeral=False
        )

    except json.JSONDecodeError:
        await interaction.followup.send("❌ 無效的 JSON 檔案內容。請確保檔案未損壞。", ephemeral=True)
    except Exception as e:
        print(f"載入檔案時發生錯誤: {e}")
        await interaction.followup.send(f"❌ 載入檔案時發生錯誤：`{e}`", ephemeral=True)


# Flask 路由 (用於 Render 部署)
@app.route('/')
def home():
    return jsonify({
        "status": "Bot is running",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
    if BOT_TOKEN:
        try:
            bot.run(BOT_TOKEN)
        except discord.errors.LoginFailure:
            print("❌ 無效的機器人 Token，請檢查 DISCORD_BOT_TOKEN 環境變數。")
        except Exception as e:
            print(f"機器人啟動時發生錯誤: {e}")
    else:
        print("❌ 請設定 DISCORD_BOT_TOKEN 環境變數。")