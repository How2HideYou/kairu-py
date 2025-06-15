"""
- 左ボタンでダブルクリックすると、ランダムなアニメーションを再生します。
- 右ボタンで一回クリックすると、再生中のアニメーションの停止を要求できます。
- 右ボタンでダブルクリックすると、終了アニメーションを再生してシャットダウンします。
- --animation-test オプションをつけて起動すると、全てのアニメーションを試すことができるボタンが出現します。
"""

import asyncio

import wx

from kairu import AnimController
from kairu.wx_backend import AgentFrame


async def dialogue_demo(agent:AgentFrame, anim_controller:AnimController):
    await anim_controller.play_animation('GREETING')
    async with anim_controller.say('やあ、ぼくはカイル！2000年代のWindowsからやってきたよ🐬'), anim_controller.play_animation('CONGRATULATE'):
        await asyncio.sleep(5)
    async with anim_controller.say('久しぶりに会えてうれしいよ！'), anim_controller.play_animation('GETATTENTION'):
        await asyncio.sleep(5)
    await anim_controller.say(None)
    await asyncio.sleep(1)
    async with anim_controller.say('えっ？'):
        await asyncio.sleep(1.5)
    async with anim_controller.say('「お前を消す方法...?」'):
        await asyncio.sleep(5)
    async with anim_controller.say('...'), anim_controller.play_animation('IDLE(1)'):
        await asyncio.sleep(5)
    async with anim_controller.say('...またね'):
        await asyncio.sleep(3)
    agent.goodbye()


if __name__ == '__main__':
    app = wx.App()
    #AgentFrame.run('DOLPHIN.ACS', dialogue_demo)
    from kairu.wx_backend.chat.chat import main
    main()