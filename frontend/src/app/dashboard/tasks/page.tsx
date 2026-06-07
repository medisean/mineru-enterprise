"use client";

import { TaskList } from "@/components/tasks/task-list";

export default function TasksPage() {
  return (
    <div className="p-8">
      <div className="max-w-5xl mx-auto">
        <TaskList titleKey="tasks.taskManagement" />
      </div>
    </div>
  );
}
