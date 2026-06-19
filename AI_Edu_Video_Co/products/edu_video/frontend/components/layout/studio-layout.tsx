"use client";

import { useState, type ReactNode } from "react";
import {
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

export type StudioLayoutProps = {
  /**
   * Video player area — always visible, never collapses.
   * Given maximum space when side panels are collapsed.
   */
  playerSlot:          ReactNode;
  /**
   * Scene thumbnail list — collapsible left panel (desktop) /
   * first tab (mobile).
   */
  sceneListSlot:       ReactNode;
  /**
   * Narration / script text panel — collapsible right panel (desktop) /
   * second tab (mobile).
   */
  scriptSlot?:         ReactNode;
  /**
   * Playback controls toolbar rendered above the player.
   */
  toolbarSlot?:        ReactNode;
  /**
   * Project title bar rendered above the toolbar.
   */
  headerSlot?:         ReactNode;
  /**
   * Quality report / feedback — bottom panel (desktop) / third tab (mobile).
   */
  detailsSlot?:        ReactNode;
  /**
   * Whether the scene list panel starts open. Default: true.
   */
  defaultSceneListOpen?: boolean;
  /**
   * Whether the script panel starts open. Default: false.
   */
  defaultScriptOpen?:  boolean;
  className?:          string;
};

// -------------------------------------------------------------------------- //
// Panel toggle button                                                          //
// -------------------------------------------------------------------------- //

function PanelToggle({
  open,
  onToggle,
  openIcon,
  closeIcon,
  label,
  centered = false,
}: {
  open:      boolean;
  onToggle:  () => void;
  openIcon:  ReactNode;
  closeIcon: ReactNode;
  label:     string;
  centered?: boolean;
}) {
  return (
    <button
      onClick={onToggle}
      aria-label={label}
      className={cn(
        "rounded-md p-1.5 text-gray-400 hover:text-gray-200",
        "hover:bg-gray-800 transition-colors focus:outline-none",
        "focus:ring-2 focus:ring-blue-500 focus:ring-offset-1",
        centered && "mx-auto"
      )}
    >
      {open ? closeIcon : openIcon}
    </button>
  );
}

// -------------------------------------------------------------------------- //
// MobileStudioTabs (internal)                                                 //
// -------------------------------------------------------------------------- //

function MobileStudioTabs({
  sceneListSlot,
  scriptSlot,
  detailsSlot,
}: {
  sceneListSlot: ReactNode;
  scriptSlot?:   ReactNode;
  detailsSlot?:  ReactNode;
}) {
  const tabs = [
    { value: "scenes", label: "Scenes",  content: sceneListSlot, always: true },
    { value: "script", label: "Script",  content: scriptSlot,    always: false },
    { value: "details",label: "Details", content: detailsSlot,   always: false },
  ].filter((t) => t.always || Boolean(t.content));

  if (tabs.length === 0) return null;

  return (
    <div className="flex-1 bg-gray-900">
      <Tabs defaultValue={tabs[0]?.value}>
        <TabsList className="w-full rounded-none border-b border-gray-800 bg-gray-900 p-0">
          {tabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className="flex-1 rounded-none border-b-2 border-transparent py-3 text-xs font-medium text-gray-400 data-[state=active]:border-blue-500 data-[state=active]:text-white data-[state=active]:bg-transparent"
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {tabs.map((tab) => (
          <TabsContent
            key={tab.value}
            value={tab.value}
            className="mt-0 overflow-y-auto max-h-[40vh]"
          >
            {tab.content}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

// -------------------------------------------------------------------------- //
// StudioLayout                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Full-bleed studio layout shell for the video editor page.
 *
 * Desktop (lg+): three-panel layout — collapsible scene list (left),
 *   player (center), collapsible script (right).
 * Mobile:        stacked — player first, then tabbed panels below.
 *
 * Uses CSS breakpoints (hidden lg:block / lg:hidden) to switch between
 * layouts without JavaScript, eliminating hydration mismatch.
 *
 * @example
 *   <StudioLayout
 *     playerSlot={<VideoPlayer />}
 *     sceneListSlot={<SceneList />}
 *     scriptSlot={<ScriptEditor />}
 *     headerSlot={<StudioHeader />}
 *     toolbarSlot={<PlaybackControls />}
 *   />
 */
export function StudioLayout({
  playerSlot,
  sceneListSlot,
  scriptSlot,
  toolbarSlot,
  headerSlot,
  detailsSlot,
  defaultSceneListOpen = true,
  defaultScriptOpen    = false,
  className,
}: StudioLayoutProps) {
  const [sceneListOpen, setSceneListOpen] = useState(defaultSceneListOpen);
  const [scriptOpen,    setScriptOpen]    = useState(defaultScriptOpen);

  // ---------------------------------------------------------------- //
  // Desktop layout (lg+)                                              //
  // ---------------------------------------------------------------- //
  const DesktopLayout = (
    <div className={cn("hidden lg:flex flex-col h-screen bg-gray-950 overflow-hidden", className)}>
      {/* Header row */}
      {headerSlot && (
        <div className="shrink-0 border-b border-gray-800 bg-gray-900">
          {headerSlot}
        </div>
      )}

      {/* Three-panel row */}
      <div className="flex flex-1 overflow-hidden">
        {/* Scene list — collapsible left panel */}
        <div
          className={cn(
            "shrink-0 border-r border-gray-800 bg-gray-900",
            "transition-[width] duration-200 ease-in-out overflow-hidden",
            sceneListOpen ? "w-64" : "w-12"
          )}
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
            {sceneListOpen && (
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                Scenes
              </span>
            )}
            <PanelToggle
              open={sceneListOpen}
              onToggle={() => setSceneListOpen((v) => !v)}
              openIcon={<PanelLeftOpen  className="h-4 w-4" />}
              closeIcon={<PanelLeftClose className="h-4 w-4" />}
              label={sceneListOpen ? "Collapse scene list" : "Expand scene list"}
              centered={!sceneListOpen}
            />
          </div>
          {sceneListOpen && (
            <div className="overflow-y-auto h-full pb-12">
              {sceneListSlot}
            </div>
          )}
        </div>

        {/* Center: toolbar + player */}
        <div className="flex flex-col flex-1 overflow-hidden">
          {toolbarSlot && (
            <div className="shrink-0 bg-gray-900 border-b border-gray-800">
              {toolbarSlot}
            </div>
          )}
          <div className="flex-1 overflow-hidden flex items-center justify-center bg-black">
            {playerSlot}
          </div>
        </div>

        {/* Script panel — collapsible right */}
        {scriptSlot && (
          <div
            className={cn(
              "shrink-0 border-l border-gray-800 bg-gray-900",
              "transition-[width] duration-200 ease-in-out overflow-hidden",
              scriptOpen ? "w-80" : "w-12"
            )}
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
              {scriptOpen && (
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Script
                </span>
              )}
              <PanelToggle
                open={scriptOpen}
                onToggle={() => setScriptOpen((v) => !v)}
                openIcon={<PanelRightOpen  className="h-4 w-4" />}
                closeIcon={<PanelRightClose className="h-4 w-4" />}
                label={scriptOpen ? "Collapse script panel" : "Show script"}
                centered={!scriptOpen}
              />
            </div>
            {scriptOpen && (
              <div className="overflow-y-auto h-full pb-12 p-4">
                {scriptSlot}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Details — bottom panel */}
      {detailsSlot && (
        <div className="shrink-0 border-t border-gray-800 bg-gray-900">
          {detailsSlot}
        </div>
      )}
    </div>
  );

  // ---------------------------------------------------------------- //
  // Mobile layout (< lg)                                              //
  // ---------------------------------------------------------------- //
  const MobileLayout = (
    <div className={cn("flex lg:hidden flex-col min-h-screen bg-gray-950", className)}>
      {/* Header */}
      {headerSlot && (
        <div className="shrink-0 border-b border-gray-800 bg-gray-900">
          {headerSlot}
        </div>
      )}

      {/* Player — aspect-video, prominent */}
      <div className="aspect-video w-full shrink-0 bg-black">
        {playerSlot}
      </div>

      {/* Toolbar below player */}
      {toolbarSlot && (
        <div className="shrink-0 bg-gray-900 border-b border-gray-800">
          {toolbarSlot}
        </div>
      )}

      {/* Tabbed panels */}
      <MobileStudioTabs
        sceneListSlot={sceneListSlot}
        scriptSlot={scriptSlot}
        detailsSlot={detailsSlot}
      />
    </div>
  );

  return (
    <>
      {DesktopLayout}
      {MobileLayout}
    </>
  );
}
