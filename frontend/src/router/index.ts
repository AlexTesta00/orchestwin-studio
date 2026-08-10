import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type Router,
  type RouterHistory,
} from "vue-router";

import HomeView from "@/views/HomeView.vue";
import LoginView from "@/views/LoginView.vue";
import ProjectDetailView from "@/views/ProjectDetailView.vue";
import ProjectsView from "@/views/ProjectsView.vue";
import RegisterView from "@/views/RegisterView.vue";

declare module "vue-router" {
  interface RouteMeta {
    requiresAuthentication?: boolean;
    guestOnly?: boolean;
  }
}

export const applicationRoutes = Object.freeze([
  {
    path: "/",
    name: "overview",
    component: HomeView,
  },
  {
    path: "/login",
    name: "login",
    component: LoginView,
    meta: {
      guestOnly: true,
    },
  },
  {
    path: "/register",
    name: "register",
    component: RegisterView,
    meta: {
      guestOnly: true,
    },
  },
  {
    path: "/projects",
    name: "projects",
    component: ProjectsView,
    meta: {
      requiresAuthentication: true,
    },
  },
  {
    path: "/projects/:projectId",
    name: "project-detail",
    component: ProjectDetailView,
    meta: {
      requiresAuthentication: true,
    },
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
