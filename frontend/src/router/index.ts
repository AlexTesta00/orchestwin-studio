import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type Router,
  type RouterHistory,
} from "vue-router";

import HomeView from "@/views/HomeView.vue";
import ProjectsView from "@/views/ProjectsView.vue";

export const applicationRoutes = Object.freeze([
  {
    path: "/",
    name: "overview",
    component: HomeView,
  },
  {
    path: "/projects",
    name: "projects",
    component: ProjectsView,
  },
] satisfies RouteRecordRaw[]);

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  return createRouter({
    history,
    routes: [...applicationRoutes],
    scrollBehavior: () => ({
      left: 0,
      top: 0,
    }),
  });
}