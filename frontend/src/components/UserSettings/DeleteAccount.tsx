import DeleteConfirmation from "./DeleteConfirmation"

const DeleteAccount = () => {
  return (
    <div className="max-w-md mt-4 rounded-lg border border-destructive/50 p-4">
      <h3 className="font-semibold text-destructive">Deactivate Account</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Deactivate your account. You will be signed out and can no longer sign
        in; your records and history are kept.
      </p>
      <DeleteConfirmation />
    </div>
  )
}

export default DeleteAccount
