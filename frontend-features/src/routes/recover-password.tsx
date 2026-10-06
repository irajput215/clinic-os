import { createFileRoute, redirect } from "@tanstack/react-router"
import { RecoverPasswordPage } from "@/features/auth/RecoverPasswordPage"
import { isSignedIn } from "@/lib/session"

export const Route = createFileRoute("/recover-password")({
  beforeLoad: () => {
    if (isSignedIn()) throw redirect({ to: "/" })
  },
  staticData: { title: "Reset your password" },
  component: RecoverPasswordPage,
})
