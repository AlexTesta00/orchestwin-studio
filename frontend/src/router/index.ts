import {
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
  type Router,
  type RouterHistory,
} from "vue-router";

import HomeView from "@/views/HomeView.vue";

declare module "vue-router" {
  interface RouteMeta {
    requiresAuthentication?: boolean;
    guestOnly?: boolean;
  }
}

const applicationRoutes = Object.freeze([
  {
    path: "/",
    name: "overview",
    component: HomeView,
  },
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: {
      guestOnly: true,
    },
  },
  {
    path: "/register",
    name: "register",
    component: () => import("@/views/RegisterView.vue"),
    meta: {
      guestOnly: true,
    },
  },
  {
    path: "/guidance",
    name: "guidance-choice",
    component: () => import("@/views/GuidanceChoiceView.vue"),
    meta: {
      requiresAuthentication: true,
    },
  },
  {
    path: "/projects",
    name: "projects",
    component: () => import("@/views/ProjectsView.vue"),
    meta: {
      requiresAuthentication: true,
    },
  },
  {
    path: "/projects/:projectId([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    name: "project-detail",
    component: () => import("@/views/ProjectDetailView.vue"),
    meta: {
      requiresAuthentication: true,
    },
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: {
      name: "overview",
      params: {},
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
