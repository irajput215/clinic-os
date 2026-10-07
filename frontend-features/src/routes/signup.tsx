import { createFileRoute, redirect } from "@tanstack/react-router"
import { SignupPage } from "@/features/auth/SignupPage"
import { isSignedIn } from "@/lib/session"

export const Route = createFileRoute("/signup")({
  beforeLoad: () => {
    if (isSignedIn()) throw redirect({ to: "/" })
  },
  staticData: { title: "Register your clinic" },
  component: SignupPage,
})
