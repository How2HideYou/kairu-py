from asyncio import Queue, run_coroutine_threadsafe
import os
import os.path
from typing import Optional

from PIL import Image

from ..acs_file import ACSFile
from ..anim_controller import AnimController, GUIBackend, AsyncEventLoopHolder
from ..wx_backend.chat.chat import ChatBackend, ChatBackendError
from ..structs import AnimInfo, FrameInfo
from ..wx_backend.agent_window import AgentFrame


class GifExportBackend(GUIBackend):
    acs:        ACSFile
    sprites:    list[Image.Image]
    gif_frames: list[tuple[Image.Image, int]] # (画像, ミリセカンド)

    def __init__(self, acs:ACSFile, event_loop_holder:Optional[AsyncEventLoopHolder]=None):
        if event_loop_holder is not None:
            super().__init__(event_loop_holder.event_loop, event_loop_holder.event_loop_thread)
        else:
            super().__init__()
        self.acs = acs
        spritesheet = Image.open(acs.spritesheet_path)
        self.sprites = [ spritesheet.crop( (left, upper, left+width, upper+height) ) for left, upper, width, height in acs.sprite_boxes ]
        self.gif_frames = []

    def play_frame(self, anim:AnimInfo, frame:FrameInfo, frame_idx:int) -> None:
        match len(frame.frame_images):
            case 1:
                self.gif_frames.append( (self.sprites[frame.frame_images[0].image_idx], frame.duration_centiseconds * 10) ) # TODO: offset
            case _:
                raise ValueError(f'複数枚の画像から構成されるフレームはサポートされていません')


class GifExportChatBackend(ChatBackend):
    gif_backend:         GifExportBackend
    gif_anim_controller: AnimController
    output_dir:          str

    def __init__(self, agent:AgentFrame, output_dir:Optional[str]=None):
        self.gif_backend = GifExportBackend(agent.acs, agent)
        self.gif_anim_controller = AnimController(
            self.gif_backend,
            agent.acs.anim_infos,
            agent.acs.character_info.state_infos,
            speed=0,
            no_idle=True,
            do_not_skip_zero_duration_frames=True
        )
        self.output_dir = output_dir or os.path.join(agent.acs._cache_dir, 'gif_output')

    def respond(self, prompt_by_user:str, output:Queue[str]):
        anim = self.gif_anim_controller.search_animation(prompt_by_user)
        if not anim:
            raise ChatBackendError(f'アニメーション {prompt_by_user} は存在しません')

        async def _coroutine():
            self.gif_backend.gif_frames.clear()
            await self.gif_anim_controller.play_animation(anim) # TODO: 無限ループするアニメーションについて
            return self.gif_backend.gif_frames
        assert self.gif_backend.event_loop

        gif_frames = run_coroutine_threadsafe(_coroutine(), self.gif_backend.event_loop).result()
        assert gif_frames
        images    = [ frame[0] for frame in gif_frames ]
        durations = [ frame[1] for frame in gif_frames ]
        os.makedirs(self.output_dir, exist_ok=True)
        images[0].save(
            os.path.join(self.output_dir, f'{anim.name}.gif'),
            save_all=True,
            append_images=images[1:],
            duration=durations,
            transparency=253,
        )
        output.put_nowait('書き出しました')