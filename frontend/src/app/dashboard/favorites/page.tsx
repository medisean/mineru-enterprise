"use client";

import { TaskList } from "@/components/tasks/task-list";

export default function FavoritesPage() {
  return (
    <div className="p-8">
      <div className="max-w-7xl mx-auto">
        <TaskList favoriteOnly titleKey="tasks.myFavorites" />
      </div>
    </div>
  );
}
